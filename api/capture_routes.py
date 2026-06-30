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

import hashlib
import json
import os
from pathlib import Path

from fastapi import APIRouter, File, Form, Header, HTTPException, UploadFile

router = APIRouter(prefix="/api/capture", tags=["capture"])

_AUDIO_DIR = os.environ.get("CONCLAVE_AUDIO_DIR", "data/audio")


def _safe_segment(value: str) -> str:
    """Filesystem-safe path segment (no traversal) from an external id."""
    return "".join(c for c in str(value) if c.isalnum() or c in "-_") or "unknown"


def _coerce_bool(value) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.lower() in ("true", "1", "yes"):
            return True
        if value.lower() in ("false", "0", "no"):
            return False
    return None


def should_store_audio(meeting_id: str, meta: dict) -> bool:
    """Resolve the per-meeting store-audio decision at the single write choke point.

    Order: (1) an explicit `store_audio` flag in the chunk metadata — the in-person
    path sets this from the recorder's toggle, and it's the most direct signal;
    (2) the per-meeting decision baked onto the `bot_invitation` at invite time
    (gMeet — already folded in the workspace default there); (3) default True
    (keep) so existing always-on behavior is unchanged when nothing opts out.
    """
    flag = _coerce_bool(meta.get("store_audio"))
    if flag is not None:
        return flag
    try:
        from infra import bot_invitations

        inv = bot_invitations.find_latest_by_native(meeting_id)
        if inv is not None and inv.get("store_audio") is not None:
            return bool(inv["store_audio"])
    except Exception:  # noqa: BLE001 — a lookup failure must never drop audio silently
        pass
    return True


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

    # Single store/no-store enforcement point (Task #30): drop the write when the
    # meeting opted out — robust regardless of which path (in-person / gMeet) produced it.
    if not should_store_audio(meeting_id, meta):
        return {
            "status": "skipped_no_store",
            "meeting_id": meeting_id,
            "chunk_seq": chunk_seq,
            "is_final": is_final == "true",
        }

    data = await file.read()
    dest_dir = Path(_AUDIO_DIR) / _safe_segment(meeting_id)
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Encrypt new captures at rest (AES-256 under the TEE-sealed key). Legacy plaintext
    # files are left untouched — reads detect the MAGIC header and fall back (no retro).
    from infra import audio_crypto

    blob = audio_crypto.encrypt(data)
    stem = f"{int(chunk_seq):06d}.{fmt}"
    (dest_dir / stem).write_bytes(blob)
    # V1 attestation seam: sha256 of the *plaintext* audio, stored as a sidecar so V1 can
    # later attest "this is the only audio captured, tamper-evident" without re-architecting.
    (dest_dir / f"{stem}.sha256").write_text(hashlib.sha256(data).hexdigest())

    return {
        "status": "stored",
        "meeting_id": meeting_id,
        "chunk_seq": chunk_seq,
        "bytes": len(data),
        "encrypted": True,
        "is_final": is_final == "true",
    }
