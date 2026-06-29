"""Diarization job-queue HTTP surface (Task #16) — worker↔Conclave seam.

Three routes, mounted under ``/api/diarize``:

  GET  /api/diarize/audio/{native_meeting_id}   audio-by-reference: the worker GETs the meeting's
                                                recording here (service-token gated, over
                                                CONCLAVE_AUDIO_DIR). Distinct from #30's user-facing
                                                signed-URL serving — this is an internal worker fetch.
  POST /api/diarize/result                      the worker POSTs ``{job_id, segments}``; we run VFTE
                                                identify-spans + the SAME two-branch reconcile that
                                                `identify_meeting` used (moved unchanged into
                                                `connectors.capture.reconcile`), then chain enrichment.
                                                Idempotent — safe to receive more than once.
  GET  /api/diarize/jobs/{job_id}               status/observability (reads the `jobs:{id}` hash).

Best-effort everywhere: a reconcile failure logs and returns; it must never wedge the worker.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel

from config import settings
from connectors.jobs import queue

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/diarize", tags=["diarize-jobs"])


def _check_service_token(authorization: str | None, expected: str) -> bool:
    """Constant-time-ish bearer check. When no token is configured we accept (dev), like the webhook."""
    if not expected:
        return True
    if not authorization or not authorization.startswith("Bearer "):
        return False
    import hmac
    return hmac.compare_digest(authorization[len("Bearer "):], expected)


@router.get("/audio/{native_meeting_id}")
def get_meeting_audio(native_meeting_id: str,
                      authorization: str | None = Header(default=None)):
    """Serve a meeting's assembled audio to a DiariZen worker (service-token gated)."""
    if not _check_service_token(authorization, settings.audio_fetch_token):
        raise HTTPException(status_code=401, detail="invalid or missing service token")
    from fastapi.responses import Response

    from connectors.capture.identify import _assemble_audio
    audio = _assemble_audio(native_meeting_id)
    if not audio:
        raise HTTPException(status_code=404, detail="no stored audio for meeting")
    return Response(content=audio, media_type="audio/wav")


class _DiarizeResult(BaseModel):
    job_id: str
    segments: list[dict]
    authoritative: bool | None = None  # worker echo; falls back to the job record / True


async def _reconcile_result(job_id: str, segments: list[dict], authoritative: bool | None,
                            *, client) -> str:
    """The result handler core (also unit-tested directly). Returns a status label.

    Idempotency: the `jobs:{id}` hash carries a ``reconciled`` flag. A redelivered callback finds it
    set and returns "duplicate" WITHOUT re-running identify-spans/reconcile — so double-delivery is a
    no-op even though the underlying merge is itself idempotent.
    """
    job = queue.get_job(job_id, client=client)
    if job is None:
        logger.warning("diarize result: unknown job %s — ignoring", job_id)
        return "unknown"
    if job.get("reconciled") == "1":
        return "duplicate"

    payload = job.get("payload_obj") or {}
    session_id = payload.get("session_id")
    native_id = payload.get("meeting_id")
    workspace = payload.get("workspace") or ""
    if authoritative is None:
        authoritative = payload.get("authoritative", "1") == "1"

    from connectors.capture.identify import _assemble_audio
    from connectors.capture.reconcile import reconcile_identity
    from infra import fpm_consent
    from transcripts import store

    session = store.load_session(session_id) if session_id else None
    if session is None:
        logger.warning("diarize result: session %s gone for job %s", session_id, job_id)
        queue.set_status(job_id, "failed", client=client, error="session not found", reconciled="1")
        return "no_session"

    audio = _assemble_audio(native_id) if native_id else b""
    vfte_ws = settings.fpm_workspace_for(workspace)
    try:
        fpm_segs = await fpm_consent.identify_spans(vfte_ws, audio, segments, tag="offline")
    except Exception as e:  # noqa: BLE001 — identity is best-effort, never wedge the worker
        logger.warning("diarize result: identify-spans for job %s failed: %s", job_id, e)
        return "identify_failed"

    reconcile_identity(session_id, session, fpm_segs, authoritative=bool(authoritative))
    # Mark reconciled BEFORE chaining enrich so a duplicate callback can't double-enqueue enrichment.
    queue.set_status(job_id, "done", client=client, reconciled="1")

    # Identity is now on resolved_speakers → run enrichment (queued or in-process). This preserves the
    # old ordering (identity before enrich) that the in-process `_identify_then_enrich` guaranteed.
    from connectors.jobs import enqueue
    try:
        enqueue.enrich(session_id, client=client)
    except Exception:  # noqa: BLE001
        logger.exception("diarize result: enrich chain for %s failed", session_id)
    return "reconciled"


@router.post("/result")
async def post_diarize_result(body: _DiarizeResult,
                              authorization: str | None = Header(default=None)) -> dict:
    """Receive a worker's diarization result → identify + reconcile + chain enrich. Idempotent."""
    if not _check_service_token(authorization, settings.diarize_result_token):
        raise HTTPException(status_code=401, detail="invalid or missing service token")
    client = queue.get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="job queue not configured (REDIS_URL unset)")
    status_label = await _reconcile_result(body.job_id, body.segments, body.authoritative,
                                           client=client)
    return {"job_id": body.job_id, "status": status_label}


@router.get("/jobs/{job_id}")
def get_diarize_job(job_id: str) -> dict:
    """Job status/observability — reads the `jobs:{id}` hash."""
    client = queue.get_client()
    if client is None:
        raise HTTPException(status_code=503, detail="job queue not configured (REDIS_URL unset)")
    job = queue.get_job(job_id, client=client)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    job.pop("payload", None)  # return the parsed payload_obj, not the raw JSON string
    return job
