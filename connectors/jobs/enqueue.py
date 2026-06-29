"""Producer helpers for the Conclave-internal job queue (enrich / regen / KB).

Call sites that today do ``asyncio.create_task(asyncio.to_thread(_enrich_in_background, sid))`` call
``enqueue.enrich(sid)`` instead. The decision is centralized here:

  * ``settings.jobs_queue`` ON and a Redis is reachable → submit a durable job onto ``conclave_jobs``
    (the in-process `worker.py` drains it; survives a restart).
  * otherwise → preserve TODAY's behavior exactly (fire an in-process background task), so default
    deployments and the whole existing test-suite are unchanged.

The job body is just ``{"session_id": …}``; the worker maps the job ``type`` back to the heavy
function. Keeping the in-process fallback byte-for-byte identical to the old call is deliberate —
this module is a seam, not a behavior change, until the flag is flipped.
"""
from __future__ import annotations

import asyncio
import logging

from config import settings
from connectors.jobs import queue

logger = logging.getLogger(__name__)

# Job type → the in-process function to run when the queue is OFF. Imported lazily (these live in
# api.transcripts_routes, which imports this package's siblings — avoid an import cycle at module load).
def _fn_for(job_type: str):
    from api import transcripts_routes as tr
    return {
        "enrich": tr._enrich_in_background,
        "regen": tr._post_approve_build,
        "kb_index": tr._kb_index_only,
        "kb_extract": tr._kb_extract_only,
    }[job_type]


def _run_in_background(job_type: str, session_id: str) -> None:
    """Today's behavior preserved EXACTLY: run the heavy fn off the request path, non-blocking.

    In an async route → `create_task(to_thread(...))` (mirrors the old webhook/upload/record call).
    In a sync route (bot post-stop ingest) → a daemon thread (mirrors the old `threading.Thread`).
    Either way the caller returns immediately; a diarization/enrich failure never blocks finalize.
    """
    fn = _fn_for(job_type)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop is not None:
        loop.create_task(asyncio.to_thread(fn, session_id))
    else:
        import threading
        threading.Thread(target=fn, args=(session_id,), daemon=True).start()


def submit_or_run(job_type: str, session_id: str, *, client=None) -> str | None:
    """Enqueue `job_type` for `session_id` when the queue is on+reachable, else run in-process.

    Returns the job_id when queued, else None.
    """
    if settings.jobs_queue:
        client = client or queue.get_client()
        if client is not None:
            job_id = queue.submit(queue.CONCLAVE_STREAM, job_type, {"session_id": session_id},
                                  client=client)
            logger.info("enqueue: %s for %s (job %s)", job_type, session_id, job_id)
            return job_id
        logger.warning("enqueue: jobs_queue on but REDIS_URL unset — running %s in-process", job_type)
    _run_in_background(job_type, session_id)
    return None


def enrich(session_id: str, *, client=None) -> str | None:
    return submit_or_run("enrich", session_id, client=client)


def regen(session_id: str, *, client=None) -> str | None:
    return submit_or_run("regen", session_id, client=client)
