"""Submit a diarization job to the durable queue (Task #16, Conclave producer side).

This replaces the blocking `diarize_client.diarize_recording(...)` call inside the finalize path.
Instead of holding a ~6-minute HTTP connection open to the single-locked DiariZen service, the
finalizer submits a job and returns; a DiariZen worker (capture repo) pulls it from the
``diarize_jobs`` stream, fetches the audio by reference, runs the engine, and POSTs the result to
``POST /api/diarize/result``.

Audio-by-reference (not bytes through Redis): the job carries an ``audio_ref`` URL the worker GETs
(`CONCLAVE_AUDIO_FETCH_URL` + native_meeting_id → the service-token-gated audio endpoint). The
``callback_url`` is where the worker POSTs ``{job_id, segments}``.

Best-effort, like the rest of finalize: if Redis/config is missing, ``submit_diarize_job`` returns
None and the caller falls back to the legacy blocking path — a queue hiccup must never block or
lose a meeting finalize (the recording stays on disk; identity can be re-run).
"""
from __future__ import annotations

import logging

from config import settings
from connectors.jobs import queue

logger = logging.getLogger(__name__)


def _audio_ref(native_meeting_id: str) -> str:
    base = settings.audio_fetch_url.rstrip("/")
    return f"{base}/{native_meeting_id}" if base else ""


def submit_diarize_job(*, session_id: str, native_meeting_id: str, workspace_id: str,
                       client=None) -> str | None:
    """Enqueue a diarize job for this meeting. Returns the job_id, or None if not submittable.

    `authoritative` is set true: a DiariZen worker is the authoritative post engine, so the result
    callback takes the overwrite branch (matching `settings.diarize_url` blocking semantics).
    """
    client = client or queue.get_client()
    if client is None:
        logger.info("submit_diarize_job: REDIS_URL unset — cannot queue %s", native_meeting_id)
        return None
    audio_ref = _audio_ref(native_meeting_id)
    callback_url = settings.diarize_result_callback_url
    if not audio_ref or not callback_url:
        logger.warning("submit_diarize_job: audio_fetch_url/callback_url unset — cannot queue %s",
                       native_meeting_id)
        return None
    payload = {
        "session_id": session_id,
        "meeting_id": native_meeting_id,
        "workspace": workspace_id,
        "audio_ref": audio_ref,
        "callback_url": callback_url,
        "authoritative": "1",
    }
    job_id = queue.submit(queue.DIARIZE_STREAM, "diarize", payload, client=client)
    logger.info("submit_diarize_job: queued %s for meeting %s (job %s)",
                session_id, native_meeting_id, job_id)
    return job_id
