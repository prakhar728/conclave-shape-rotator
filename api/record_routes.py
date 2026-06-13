"""In-person Record ingress — Conclave ingress mode 3 (bot · upload · record).

POST /api/workspaces/{workspace_id}/record   (multipart: file=<audio>, intent?)

A clip recorded in the browser is orchestrated server-side: sent to FPM
(`/v1/diarize`, which diarizes AND identifies against the workspace's consented
voiceprints) and, in parallel, to the NEAR Whisper transcription-service for the
words. The two are merged by timestamp into `[speaker] text` segments and handed
to the SAME ingest path the paste/upload endpoint uses — so a recorded meeting
becomes an ordinary Conclave session (reusing meeting/[id]) for free.

The FPM and transcription tokens live in server config, never in the browser, and
FPM is the only place consent is enforced (a "stay anonymous" speaker comes back
unnamed; a forgotten one comes back as an unknown speaker). Audio is processed and
discarded here — only the derived transcript is stored.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from api.workspaces_routes import _require_member
from auth.session import require_current_user
from config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["record"])

#: cap on an uploaded recording (~25 MB ≈ several minutes of opus/webm).
MAX_AUDIO_BYTES = 25 * 1024 * 1024


def _best_overlap(start: float, end: float, idsegs: list[dict]) -> Optional[dict]:
    """The identity segment with the most time-overlap with [start, end]."""
    best, best_ov = None, 0.0
    for d in idsegs:
        ds, de = float(d.get("start") or 0.0), float(d.get("end") or 0.0)
        ov = min(end, de) - max(start, ds)
        if ov > best_ov:
            best, best_ov = d, ov
    if best is not None:
        return best
    mid = (start + end) / 2.0
    for d in idsegs:  # fallback: the segment whose span contains the ASR midpoint
        if float(d.get("start") or 0.0) <= mid <= float(d.get("end") or 0.0):
            return d
    return idsegs[0] if idsegs else None


def merge_by_timestamp(asr_segments: list[dict], identity_segments: list[dict]) -> list[dict]:
    """ASR words ∥ FPM identity → `[{speaker, text, start, end}]` (the batch merge).

    Speakers are numbered globally by first appearance; a named voiceprint shows its
    name, an anonymous/suppressed one shows `Speaker N`. So 2 known + 1 unknown reads
    as `[Alice] … [Bob] … [Speaker 3] …`.
    """
    idsegs = sorted(identity_segments, key=lambda s: float(s.get("start") or 0.0))

    def key_of(d: dict) -> str:
        return d.get("local_speaker") or d.get("voiceprint_id") or "spk"

    index: dict[str, int] = {}
    for d in idsegs:
        index.setdefault(key_of(d), len(index) + 1)

    def label_for(d: Optional[dict]) -> str:
        if d is None:
            return "Speaker 1"
        return d.get("name") or f"Speaker {index.get(key_of(d), '?')}"

    out: list[dict] = []
    for a in asr_segments:
        text = (a.get("text") or "").strip()
        if not text:
            continue
        start = float(a.get("start") or 0.0)
        end = float(a.get("end") or start)
        out.append({
            "speaker": label_for(_best_overlap(start, end, idsegs)),
            "text": text,
            "start": round(start, 3),
            "end": round(end, 3),
        })
    return out


async def _fpm_diarize(client, audio: bytes, filename: str, content_type: str,
                       fpm_workspace: str) -> list[dict]:
    """Call FPM /v1/diarize (offline) → identity segments (final corrected view)."""
    headers = {"Authorization": f"Bearer {settings.fpm_api_token}"} if settings.fpm_api_token else {}
    resp = await client.post(
        f"{settings.fpm_base_url.rstrip('/')}/v1/diarize",
        headers=headers,
        files={"file": (filename, audio, content_type)},
        data={"workspace": fpm_workspace, "tag": "offline"},
    )
    if resp.status_code != 200:
        raise HTTPException(502, f"FPM diarize failed ({resp.status_code}): {resp.text[:200]}")
    final, streamed = None, []
    for line in resp.text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if obj.get("type") == "transcript":
            final = obj.get("segments", [])
        elif "start" in obj:
            streamed.append(obj)
    return final if final is not None else streamed


async def _transcribe(client, audio: bytes, filename: str, content_type: str) -> list[dict]:
    """Call the NEAR Whisper transcription-service → ASR segments with timestamps."""
    headers = ({"Authorization": f"Bearer {settings.transcription_service_token}"}
               if settings.transcription_service_token else {})
    resp = await client.post(
        f"{settings.transcription_service_url.rstrip('/')}/v1/audio/transcriptions",
        headers=headers,
        files={"file": (filename, audio, content_type)},
        data={"model": settings.transcription_model, "response_format": "verbose_json"},
    )
    if resp.status_code != 200:
        raise HTTPException(502, f"transcription failed ({resp.status_code}): {resp.text[:200]}")
    return resp.json().get("segments", [])


@router.post("/{workspace_id}/record", status_code=status.HTTP_202_ACCEPTED)
async def record_meeting(
    workspace_id: str,
    file: UploadFile = File(...),
    intent: Optional[str] = Form(default=None),
    user: dict = Depends(require_current_user),
):
    """Ingest an in-person recording → identified, transcribed Conclave meeting.

    202 {session_id, is_processing: true} — same envelope as upload; enrichment +
    KB indexing run in the background. Re-ingesting identical audio is a 200 no-op.
    """
    _require_member(workspace_id, user["id"])
    if not settings.record_meeting_enabled():
        raise HTTPException(503, "in-person recording is not configured on this server")

    audio = await file.read()
    if not audio:
        raise HTTPException(400, "empty recording")
    if len(audio) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "recording exceeds the 25MB limit")
    filename = file.filename or "recording.webm"
    content_type = file.content_type or "audio/webm"

    import asyncio

    import httpx

    fpm_ws = settings.fpm_workspace_for(workspace_id)
    async with httpx.AsyncClient(timeout=180.0) as client:
        identity, asr = await asyncio.gather(
            _fpm_diarize(client, audio, filename, content_type, fpm_ws),
            _transcribe(client, audio, filename, content_type),
        )

    merged = merge_by_timestamp(asr, identity)
    if not merged:
        raise HTTPException(422, "no speech transcribed from the recording")

    # Hand the merged segments to the EXACT upload ingest path (no new pipeline).
    from api.upload_routes import (
        UploadTranscriptBody,
        _parse_upload,
        _scoped_session_id,
    )

    text = json.dumps(merged)
    body = UploadTranscriptBody(text=text, filename=filename, intent=intent)
    ni = _parse_upload(body)
    session_id = _scoped_session_id(workspace_id, ni, text)

    from transcripts import store

    if store.load_session(session_id) is not None:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={"session_id": session_id, "is_processing": False, "status": "duplicate"},
        )

    from transcripts.identity import resolve_speakers
    from transcripts.parse import build_session

    session = build_session(ni, session_id=session_id)
    session.metadata.resolved_speakers = resolve_speakers(session)
    if intent and intent.strip():
        session.metadata.raw_intent = intent.strip()
    store.save_session(session)
    store.set_workspace(
        session.session_id,
        workspace_id=workspace_id,
        owner_user_id=user["id"],
        visibility="owner-only",
    )

    from api.transcripts_routes import _enrich_in_background

    asyncio.create_task(asyncio.to_thread(_enrich_in_background, session.session_id))

    return {"session_id": session.session_id, "is_processing": True,
            "speakers": sorted({m["speaker"] for m in merged}), "status": "accepted"}
