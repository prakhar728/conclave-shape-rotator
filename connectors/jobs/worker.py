"""In-process Conclave worker — drains the ``conclave_jobs`` stream (enrich / regen / KB).

Mirrors `connectors/capture/consumer.py`'s lifecycle (``start()`` on app startup, ``stop()`` on
shutdown; a no-op if ``REDIS_URL`` is unset). Where the segment consumer just buffers, this worker
runs the heavy post-processing functions durably: a job that was mid-flight when Conclave restarted
is reclaimed from the pending list (``XAUTOCLAIM``) and re-run, and a job that keeps failing is
dead-lettered after `max_attempts`.

`process_message` is the unit the tests drive directly (no event loop, no real Redis) — it dispatches
by job ``type`` to the same functions the in-process fallback calls, so queued and inline execution
are behaviorally identical.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os

from connectors.jobs import queue

logger = logging.getLogger(__name__)

CONSUMER = os.environ.get("CONCLAVE_JOBS_CONSUMER", "conclave-worker-1")

_task: "asyncio.Task | None" = None
_stop = False


def _handler_for(job_type: str):
    """Map a job type → its heavy function (imported lazily to avoid an import cycle)."""
    from api import transcripts_routes as tr
    return {
        "enrich": tr._enrich_in_background,
        "regen": tr._post_approve_build,
        "kb_index": tr._kb_index_only,
        "kb_extract": tr._kb_extract_only,
    }.get(job_type)


def process_message(fields: dict, *, client, stream: str = None, group: str = None,
                    msg_id: str = None) -> str:
    """Run ONE job. Returns "done" | "failed" | "skipped".

    Bumps the delivery count first; past `max_attempts` the job is dead-lettered (so a poison job
    can't cycle forever). On a handler exception the message is left UN-ACKed → it stays pending and
    a later `reclaim_stale` re-delivers it. The caller ACKs only on a clean "done"/"skipped".
    """
    stream = stream or queue.CONCLAVE_STREAM
    group = group or queue.CONCLAVE_GROUP
    job_id = fields.get("job_id")
    job_type = fields.get("type")
    payload = json.loads(fields.get("payload") or "{}")
    session_id = payload.get("session_id")

    if job_id:
        attempts = queue.incr_attempts(job_id, client=client)
        if attempts > queue.max_attempts():
            logger.warning("conclave worker: job %s (%s) exceeded %d attempts — dead-lettering",
                           job_id, job_type, queue.max_attempts())
            if msg_id is not None:
                queue.dead_letter(stream, group, msg_id, fields, job_id, client=client,
                                  error="max attempts exceeded")
            return "failed"
        queue.set_status(job_id, "processing", client=client)

    handler = _handler_for(job_type)
    if handler is None or not session_id:
        logger.warning("conclave worker: unknown job type %r / no session — skipping %s",
                       job_type, job_id)
        if job_id:
            queue.set_status(job_id, "done", client=client, note="noop")
        if msg_id is not None:
            queue.ack(stream, group, msg_id, client=client)
        return "skipped"

    handler(session_id)  # raises → caller leaves it pending for reclaim
    if job_id:
        queue.set_status(job_id, "done", client=client)
    if msg_id is not None:
        queue.ack(stream, group, msg_id, client=client)
    return "done"


def _poll_once(client, *, stream: str, group: str, consumer: str) -> int:
    """One reclaim+read tick: reprocess stale pending entries, then new ones. Returns #handled."""
    handled = 0
    for msg_id, fields in queue.reclaim_stale(stream, group, consumer, client=client):
        try:
            process_message(fields, client=client, stream=stream, group=group, msg_id=msg_id)
        except Exception:  # noqa: BLE001 — un-acked, reclaimed again next tick
            logger.exception("conclave worker: reclaimed job %s failed", fields.get("job_id"))
        handled += 1
    for msg_id, fields in queue.read_new(stream, group, consumer, client=client):
        try:
            process_message(fields, client=client, stream=stream, group=group, msg_id=msg_id)
        except Exception:  # noqa: BLE001 — left pending; a later tick reclaims + retries it
            logger.exception("conclave worker: job %s failed", fields.get("job_id"))
        handled += 1
    return handled


async def _consume() -> None:
    client = queue.get_client()
    if client is None:
        logger.info("conclave worker: REDIS_URL unset — internal job queue disabled")
        return
    stream, group = queue.CONCLAVE_STREAM, queue.CONCLAVE_GROUP
    queue.ensure_group(stream, group, client=client)
    logger.info("conclave worker: draining %s as %s/%s", stream, group, CONSUMER)
    while not _stop:
        try:
            n = await asyncio.to_thread(_poll_once, client, stream=stream, group=group, consumer=CONSUMER)
        except asyncio.CancelledError:
            break
        except Exception as e:  # noqa: BLE001 — keep the loop alive across blips
            logger.warning("conclave worker: poll error (%s) — retrying", e)
            n = 0
        if n == 0:
            await asyncio.sleep(1)  # idle backoff (read_new uses block=0 in thread mode)


def start() -> None:
    """Launch the worker as a background task (no-op if already running / REDIS_URL unset)."""
    global _task, _stop
    if _task is not None and not _task.done():
        return
    _stop = False
    _task = asyncio.create_task(_consume())


async def stop() -> None:
    global _stop
    _stop = True
    if _task is not None:
        try:
            await asyncio.wait_for(asyncio.shield(_task), timeout=5)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            _task.cancel()
        except Exception:  # noqa: BLE001
            pass
