"""Host-triggered contribution of a meeting to Shape Rotator OS (Task #20).

`POST /api/meetings/{session_id}/contribute-shapeos`  (host/owner only)

One click = Arm 1: push the host-approved **v2** transcript to Shape OS's public
anon `context_submissions` inbox (`infra/shape_contrib.contribute_raw`). Nothing
fires automatically — the meeting page shows a "Contribute to Shape Rotator OS"
button, enabled only after the host approves the v2 transcript, and a confirm
dialog is the consent/opt-in. This route re-enforces both gates server-side:

  * owner-only (workspace sessions); and
  * v2 **approved** — we never ship raw ASR, only the host-corrected transcript
    (`store.v2_segments_or_raw` returns the corrected v2 once approved).

Arm 2 (distilled readout → PR) is intentionally absent — see
`infra/shape_contrib` for why (upstream moved transcript content off-repo).
"""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException, Request

from config import settings
from infra import shape_contrib
from transcripts import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/meetings", tags=["shape-contrib"])


def _require_owner(request: Request, session_id: str) -> dict:
    """Auth + owner gate (mirrors transcripts_routes._require_editor): 401 unauth ·
    404 no session · 403 not owner. Legacy cohort sessions (no workspace row) are
    editable/contributable by any authed user, same as the rest of the editor API."""
    from auth.session import try_current_user

    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    if store.load_session(session_id) is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    try:
        ws = store.get_workspace_fields(session_id)
    except Exception:  # noqa: BLE001 — defensive against test-DB schema drift
        ws = None
    if ws and ws.get("workspace_id") and ws.get("owner_user_id") != user["id"]:
        raise HTTPException(status_code=403, detail="only the owner can contribute")
    return user


@router.post("/{session_id}/contribute-shapeos")
def contribute_shapeos(session_id: str, request: Request) -> dict:
    """Run Arm 1 for one meeting. Returns ``{"inbox": {...}}``.

    Gated: owner-only + v2 must be **approved** (409 otherwise) so the readout is
    built from the corrected transcript, not raw ASR. ``CONCLAVE_SHAPEOS_CONTRIB_DRY_RUN``
    short-circuits the network call (dev safety)."""
    _require_owner(request, session_id)

    v2 = store.load_v2(session_id)
    if v2 is None or v2.status != "approved":
        raise HTTPException(
            status_code=409,
            detail="approve the v2 transcript before contributing",
        )

    segments = store.v2_segments_or_raw(session_id)  # corrected v2 (approved)
    session = store.load_session(session_id)
    meta = session.metadata if session else None
    date: Optional[str] = getattr(meta, "date", None)
    source: Optional[str] = getattr(meta, "source", None)
    ws = None
    try:
        ws = store.get_workspace_fields(session_id)
    except Exception:  # noqa: BLE001
        ws = None

    title = f"In-person session — {date}" if date else "In-person session"
    metadata = {
        "conclave_session_id": session_id,
        **({"date": date} if date else {}),
        **({"source": source} if source else {}),
        **({"workspace_id": ws["workspace_id"]} if ws and ws.get("workspace_id") else {}),
    }

    result = shape_contrib.contribute_raw(
        segments=segments,
        title=title,
        metadata=metadata,
        url=settings.shapeos_supabase_url,
        anon_key=settings.shapeos_anon_key,
        dry_run=settings.shapeos_contrib_dry_run,
    )
    if not result.ok:
        logger.warning(
            "shapeos contribute failed session=%s status=%s http=%s",
            session_id, result.status, result.http_statuses,
        )
    return {"inbox": result.to_dict()}
