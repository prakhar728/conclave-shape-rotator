"""Transcript upload HTTP surface — paste/file upload into a workspace.

POST /api/workspaces/{workspace_id}/transcripts

Auth stack copied from kb_routes: require_current_user + _require_member
(404 — not 403 — for non-members, so existence never leaks). Parsing
reuses transcripts.sources/parse verbatim; persistence and the background
enrichment chain are the SAME calls the Recato webhook makes
(api/transcripts_routes.py) — this endpoint adds no new pipeline code,
only a new way in.

Session-id derivation is workspace-scoped (`upload-{ws8}-{slug|hash}`):
the bare filename slug that file-ingest uses would be a *global* key, so
two tenants uploading `notes.txt` would collide and the second would see
the first's session. Scoping by workspace keeps idempotency (same file
re-uploaded into the same workspace → same id → 200) without the leak.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from api.workspaces_routes import _require_member
from auth.session import require_current_user
from transcripts import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["upload"])

#: Pydantic-enforced cap on pasted/uploaded transcript text (~2 MB).
MAX_TEXT_BYTES = 2 * 1024 * 1024


class UploadTranscriptBody(BaseModel):
    filename: Optional[str] = Field(default=None, max_length=255)
    # max_length counts characters; combined with the byte check in the
    # handler this bounds memory without rejecting multi-byte text early.
    text: str = Field(min_length=1, max_length=MAX_TEXT_BYTES)
    # Optional freeform "focus / what to capture" — grounds enrichment
    # (transcripts/compile_intent.py).
    intent: Optional[str] = Field(default=None, max_length=4000)


def _parse_upload(body: UploadTranscriptBody):
    """Text → NormalizedInput via the existing readers (no new parser).

    JSON-looking text is parsed and routed through the dict/list reader
    (VoxTerm/generic shapes); anything else goes down the Otter-text path.
    422 on anything that yields zero segments — junk is never stored.
    """
    from transcripts.sources import read_obj

    if len(body.text.encode("utf-8")) > MAX_TEXT_BYTES:
        raise HTTPException(
            status_code=422,
            detail="transcript exceeds the 2MB limit",
        )

    stripped = body.text.lstrip()
    obj: object = body.text
    if stripped[:1] in "[{":
        try:
            obj = json.loads(body.text)
        except json.JSONDecodeError:
            obj = body.text  # JSON-ish but not JSON → try as Otter text

    try:
        ni = read_obj(obj, path=body.filename)
    except Exception:
        logger.exception("upload parse failed")
        ni = None
    if ni is None or not ni.segments:
        raise HTTPException(
            status_code=422,
            detail=(
                "could not parse any transcript segments — expected"
                " Otter-style 'Speaker  M:SS' text or a supported JSON shape"
            ),
        )
    return ni


def _scoped_session_id(workspace_id: str, ni, text: str) -> str:
    """Deterministic, workspace-scoped id (see module docstring)."""
    base = ni.provenance.get("session_id")  # filename slug, when given
    if not base:
        base = hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    ws8 = workspace_id.replace("ws_", "")[:8]
    return f"upload-{ws8}-{base}-{h}"


@router.post("/{workspace_id}/transcripts", status_code=status.HTTP_202_ACCEPTED)
async def upload_transcript(
    workspace_id: str,
    body: UploadTranscriptBody,
    user: dict = Depends(require_current_user),
):
    """Upload a transcript (pasted text or client-read file) into a workspace.

    202 {session_id, is_processing: true} — enrichment + KB indexing run
    in the background exactly as for webhook-ingested meetings. Re-upload
    of identical content into the same workspace is a 200 no-op.
    """
    _require_member(workspace_id, user["id"])

    ni = _parse_upload(body)
    session_id = _scoped_session_id(workspace_id, ni, body.text)

    # Idempotency: same content, same workspace → the session already
    # exists; hand it back rather than erroring (raw is write-once). Surface the
    # existing v2's state so the UI can say "already imported (approved <date>)"
    # instead of silently dropping the user into a frozen editor.
    existing = store.load_session(session_id)
    if existing is not None:
        from fastapi.responses import JSONResponse

        v2 = store.load_v2(session_id)
        return JSONResponse(
            status_code=status.HTTP_200_OK,
            content={
                "session_id": session_id, "is_processing": False, "status": "duplicate",
                "v2_status": v2.status if v2 else None,
                "approved_at": v2.approved_at if v2 else None,
            },
        )

    from transcripts.identity import resolve_speakers
    from transcripts.parse import build_session

    session = build_session(ni, session_id=session_id)
    session.metadata.resolved_speakers = resolve_speakers(session)
    if body.intent and body.intent.strip():
        session.metadata.raw_intent = body.intent.strip()
    store.save_session(session)
    store.set_workspace(
        session.session_id,
        workspace_id=workspace_id,
        owner_user_id=user["id"],
        visibility="owner-only",
    )

    # Same background chain as the webhook: enrichment → magic links →
    # KB indexing → flagged extraction. Durable via the job queue when on (Task #16),
    # else the same in-process background task as before.
    from connectors.jobs import enqueue

    enqueue.enrich(session.session_id)

    return {"session_id": session.session_id, "is_processing": True,
            "status": "accepted"}
