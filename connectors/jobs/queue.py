"""Redis-Streams job-queue core — durable submit / claim / ack / reclaim / dead-letter.

This is the shared substrate for Task #16. It mirrors the primitives already proven in
`connectors/capture/consumer.py` (`xgroup_create` + `xreadgroup` + `xack`) and adds the two
things a *job* queue needs that a segment stream doesn't: a per-job status record and
crash-recovery.

Durability model (the whole point):
  * ``submit`` writes a ``jobs:{id}`` hash (status source of truth) AND ``XADD``s the stream.
    The hash + stream entry live in Redis, so a Conclave/worker restart loses NOTHING — a
    submitted job is still there to be claimed.
  * A consumer claims via ``XREADGROUP >`` (new) and processes. On success it ``XACK``s.
  * If a worker dies mid-job it never ACKs, so the entry stays PENDING. ``reclaim`` (``XAUTOCLAIM``)
    hands idle pending entries to a live worker → the job completes, never lost.
  * Each delivery bumps ``attempts``; past ``max_attempts`` the job is dead-lettered
    (``{stream}:dead``) + marked ``failed`` + ACKed (so it stops cycling).

Why two streams, not one: diarize jobs must run on the GPU/DiariZen worker (capture repo);
enrich/regen/KB jobs need Conclave's DB + LLM. A single Redis consumer *group* round-robins
messages across its consumers, so heterogeneous workers can't share one group/stream without
one claiming a job it can't run. Two streams (`diarize_jobs`, `conclave_jobs`), each with its
own group, is the runtime-correct split. The *record shape* is generalized with a ``type`` field
("typed jobs"), and this module is stream-agnostic — both streams use it.

The Redis client is always passed in (no module-global client): production callers pass
``get_client()``; tests pass a ``fakeredis`` instance. Everything is ``decode_responses=True``
(str in / str out), so hash values are strings — structured payloads ride as a JSON ``payload``
field.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid

logger = logging.getLogger(__name__)

# Stream names (env-overridable; defaults match the handoff + capture worker config).
DIARIZE_STREAM = os.environ.get("CONCLAVE_DIARIZE_JOBS_STREAM", "diarize_jobs")
CONCLAVE_STREAM = os.environ.get("CONCLAVE_JOBS_STREAM", "conclave_jobs")

# Consumer-group + retry knobs.
DIARIZE_GROUP = os.environ.get("CONCLAVE_DIARIZE_JOBS_GROUP", "diarize-workers")
CONCLAVE_GROUP = os.environ.get("CONCLAVE_JOBS_GROUP", "conclave-workers")


def max_attempts() -> int:
    """Deliveries before a job is dead-lettered (read live so tests can override)."""
    try:
        return int(os.environ.get("CONCLAVE_JOBS_MAX_ATTEMPTS", "3"))
    except ValueError:
        return 3


def reclaim_min_idle_ms() -> int:
    """How long a pending entry must sit idle before another worker may reclaim it."""
    try:
        return int(os.environ.get("CONCLAVE_JOBS_RECLAIM_IDLE_MS", "60000"))
    except ValueError:
        return 60000


def redis_url() -> str | None:
    return os.environ.get("REDIS_URL")


def get_client():
    """Real Redis client for production callers (lazy import, no-op-friendly).

    Returns None if ``REDIS_URL`` is unset — callers fall back to the in-process path,
    exactly like `consumer.py` does, so non-streaming deployments + tests are unaffected.
    """
    url = redis_url()
    if not url:
        return None
    import redis  # lazy: only needed when the queue is configured

    return redis.from_url(url, decode_responses=True)


def _job_key(job_id: str) -> str:
    return f"jobs:{job_id}"


# ── producer side ───────────────────────────────────────────────────────────

def submit(stream: str, job_type: str, payload: dict, *, client) -> str:
    """Create a durable job: write the ``jobs:{id}`` status hash, then ``XADD`` the stream.

    `payload` is the job's structured body ({meeting_id, session_id, …}); it rides as a JSON
    string on both the hash and the stream entry. Returns the new ``job_id``. Hash first so a
    claim can never observe a stream entry without its status record.
    """
    job_id = uuid.uuid4().hex
    payload_json = json.dumps(payload)
    client.hset(_job_key(job_id), mapping={
        "job_id": job_id,
        "type": job_type,
        "status": "queued",
        "attempts": "0",
        "created_at": str(time.time()),
        "payload": payload_json,
    })
    client.xadd(stream, {"job_id": job_id, "type": job_type, "payload": payload_json})
    return job_id


# ── status record (jobs:{id} hash) ──────────────────────────────────────────

def get_job(job_id: str, *, client) -> dict | None:
    rec = client.hgetall(_job_key(job_id))
    if not rec:
        return None
    if rec.get("payload"):
        try:
            rec["payload_obj"] = json.loads(rec["payload"])
        except ValueError:
            rec["payload_obj"] = {}
    return rec


def set_status(job_id: str, status: str, *, client, **extra) -> None:
    mapping = {"status": status, "updated_at": str(time.time())}
    mapping.update({k: str(v) for k, v in extra.items()})
    client.hset(_job_key(job_id), mapping=mapping)


def incr_attempts(job_id: str, *, client) -> int:
    """Bump and return the delivery count for this job (atomic)."""
    return int(client.hincrby(_job_key(job_id), "attempts", 1))


# ── consumer side ───────────────────────────────────────────────────────────

def ensure_group(stream: str, group: str, *, client) -> None:
    """Idempotently create the consumer group (and the stream, via ``mkstream``)."""
    import redis  # for ResponseError type

    try:
        client.xgroup_create(stream, group, id="0", mkstream=True)
    except redis.exceptions.ResponseError as e:  # type: ignore[attr-defined]
        if "BUSYGROUP" not in str(e):  # already exists → fine
            raise


def _flatten(resp) -> list[tuple[str, dict]]:
    out: list[tuple[str, dict]] = []
    for _stream_key, messages in resp or []:
        for msg_id, fields in messages:
            if fields:  # XAUTOCLAIM can surface tombstones (None fields) — skip them
                out.append((msg_id, fields))
    return out


def read_new(stream: str, group: str, consumer: str, *, client, count: int = 16,
             block_ms: int = 2000) -> list[tuple[str, dict]]:
    """Claim never-before-delivered entries (``>``). Blocks up to ``block_ms``."""
    resp = client.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
    return _flatten(resp)


def reclaim_stale(stream: str, group: str, consumer: str, *, client, count: int = 16,
                  min_idle_ms: int | None = None) -> list[tuple[str, dict]]:
    """Reclaim pending entries idle longer than ``min_idle_ms`` (crashed-worker recovery).

    ``XAUTOCLAIM`` transfers ownership of stale pending entries to ``consumer`` and returns them
    for reprocessing — this is what makes a killed worker's in-flight job complete instead of
    being lost.
    """
    idle = reclaim_min_idle_ms() if min_idle_ms is None else min_idle_ms
    res = client.xautoclaim(stream, group, consumer, idle, "0-0", count=count)
    # redis-py returns (next_cursor, claimed[, deleted]); fakeredis matches.
    claimed = res[1] if len(res) >= 2 else []
    return _flatten([(stream, claimed)])


def ack(stream: str, group: str, msg_id: str, *, client) -> None:
    client.xack(stream, group, msg_id)


def dead_letter(stream: str, group: str, msg_id: str, fields: dict, job_id: str, *,
                client, error: str = "") -> None:
    """Move a poison/over-retried job to ``{stream}:dead``, mark it failed, and ACK it.

    ACK is essential: it removes the entry from the pending list so it stops being reclaimed
    and cycling forever. The dead-letter stream keeps the payload for inspection/replay.
    """
    client.xadd(f"{stream}:dead", {**fields, "error": error[:300]})
    set_status(job_id, "failed", client=client, error=error[:300])
    ack(stream, group, msg_id, client=client)
