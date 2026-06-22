"""Capture → Conclave: receive streamed audio chunks (P1).

The capture bot's `RecordingService.uploadChunk` POSTs audio chunks here — this
is the `recordingUploadUrl` Conclave hands the bot at launch, *instead* of
Recato's meeting-api. Audio lands in Conclave's TEE so post-meeting diarization
(DiariZen, P3) and voice identity (VFTE, P4) can use it; nothing audio-related
persists on the stateless capture side.

Multipart contract mirrors the bot (`recato-bot/.../services/recording.ts`):
  - `metadata` (JSON): {meeting_id, session_uid, format, chunk_seq, is_final, ...}
  - `chunk_seq` (form), `is_final` (form), `file` (audio bytes)

Stored at `CONCLAVE_AUDIO_DIR/{meeting_id}/{chunk_seq}.{format}`. Optional bearer
auth (enforced only when `CONCLAVE_CAPTURE_INGEST_SECRET` is set — dev-friendly,
mirrors the webhook receiver). Real TEE-sealed storage + mandatory auth = P5.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

router = APIRouter(prefix="/api/capture", tags=["capture"])

_AUDIO_DIR = os.environ.get("CONCLAVE_AUDIO_DIR", "data/audio")


def _safe_segment(value: str) -> str:
    """Filesystem-safe path segment (no traversal) from an external id."""
    return "".join(c for c in str(value) if c.isalnum() or c in "-_") or "unknown"


def _check_auth(authorization: str | None) -> None:
    secret = os.environ.get("CONCLAVE_CAPTURE_INGEST_SECRET")
    if not secret:
        return  # dev: unauthenticated accepted (hardened in P5)
    presented = ""
    if authorization and authorization.startswith("Bearer "):
        presented = authorization[len("Bearer "):]
    if presented != secret:
        raise HTTPException(status_code=401, detail="invalid capture ingest token")


@router.post("/audio-chunk")
async def audio_chunk(
    file: UploadFile = File(...),
    metadata: str = Form(...),
    chunk_seq: int = Form(...),
    is_final: str = Form("false"),
    authorization: str | None = Header(default=None),
) -> dict:
    _check_auth(authorization)
    try:
        meta = json.loads(metadata)
    except (ValueError, TypeError):
        raise HTTPException(status_code=400, detail="metadata must be valid JSON")
    meeting_id = meta.get("meeting_id")
    if not meeting_id:
        raise HTTPException(status_code=400, detail="metadata.meeting_id is required")
    fmt = _safe_segment(meta.get("format") or "webm")

    data = await file.read()
    dest_dir = Path(_AUDIO_DIR) / _safe_segment(meeting_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    (dest_dir / f"{int(chunk_seq):06d}.{fmt}").write_bytes(data)

    return {
        "status": "stored",
        "meeting_id": meeting_id,
        "chunk_seq": chunk_seq,
        "bytes": len(data),
        "is_final": is_final == "true",
    }
