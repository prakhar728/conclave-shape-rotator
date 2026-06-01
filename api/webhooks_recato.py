"""Recato `meeting.completed` webhook receiver.

Mounted at POST /api/webhooks/recato/meeting-completed. Replaces the
separate `connectors.recato.consumer` service for the v1 hosted product
(BUILD_DOC §10.5). The standalone consumer.py stays for users running
Recato as a third-party producer; ours is the in-process path.

Flow:
  1. Verify Recato's HMAC signature (`X-Signature: sha256=<hex>`,
     `RECATO_WEBHOOK_SECRET` env var). Optional for dev — when the secret
     is unset we accept unsigned hooks but log a warning.
  2. Ignore non-`meeting.completed` events.
  3. Fetch full transcript from Recato.
  4. Translate Recato → canonical, build a Session.
  5. Look up the bot_invitation for this Meet to recover the inviter +
     workspace; bind the session via save_session_with_workspace.
  6. Kick async enrichment (mirrors /transcripts/ingest).
  7. Mark the invitation 'completed'. Phase 2.8 will hook here for the
     post-enrichment email blast.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel

from connectors.recato.cli import _env  # for the fetch URL parts
from connectors.recato.translator import to_canonical
from infra import bot_invitations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks/recato", tags=["webhooks"])


class _MeetingCompletedEvent(BaseModel):
    """Subset of Recato's outbound envelope we actually consume."""
    event_id: str
    event_type: str
    api_version: str
    created_at: str
    data: dict[str, Any]


def _verify(body: bytes, header: Optional[str], secret: str) -> bool:
    if not header or not header.startswith("sha256="):
        return False
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(f"sha256={expected}", header)


def _fetch_recato_transcript(platform: str, native_meeting_id: str) -> dict:
    """GET the full transcript Recato exposed for this meeting."""
    import httpx

    base = (os.environ.get("RECATO_API_BASE_URL") or "").rstrip("/")
    token = os.environ.get("RECATO_API_TOKEN") or ""
    if not base or not token:
        raise HTTPException(
            status_code=502, detail="Recato is not configured on this host"
        )
    url = f"{base}/transcripts/{platform}/{native_meeting_id}"
    try:
        resp = httpx.get(
            url,
            headers={
                "X-API-Key": token,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=30.0,
        )
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail=f"Recato unreachable: {e}") from e
    if resp.status_code != 200:
        raise HTTPException(
            status_code=502,
            detail=f"Recato GET transcript {resp.status_code}: {resp.text[:200]}",
        )
    return resp.json()


@router.post("/meeting-completed", status_code=status.HTTP_202_ACCEPTED)
async def on_meeting_completed(
    request: Request,
    payload: _MeetingCompletedEvent,
    x_signature: Optional[str] = Header(default=None, alias="X-Signature"),
) -> dict:
    """Drive: Recato → fetch → translate → bind to workspace → enrich."""
    # 1. Auth.
    secret = os.environ.get("RECATO_WEBHOOK_SECRET")
    if secret:
        raw = await request.body()
        if not _verify(raw, x_signature, secret):
            raise HTTPException(status_code=401, detail="signature mismatch")
    else:
        logger.warning(
            "RECATO_WEBHOOK_SECRET not set — accepting unsigned webhook (dev only)"
        )

    # 2. Filter.
    if payload.event_type != "meeting.completed":
        return {"status": "ignored", "reason": f"event_type {payload.event_type!r}"}
    meeting = payload.data.get("meeting") or {}
    if meeting.get("status") and meeting.get("status") != "completed":
        return {
            "status": "ignored",
            "reason": f"meeting.status {meeting.get('status')!r}",
        }
    platform = meeting.get("platform")
    native_id = meeting.get("native_meeting_id")
    if not platform or not native_id:
        raise HTTPException(
            status_code=400,
            detail="meeting.platform and meeting.native_meeting_id are required",
        )

    # 3. Fetch transcript from Recato.
    vexa = _fetch_recato_transcript(platform, native_id)
    if not (vexa.get("segments") or []):
        # Empty transcripts happen (silence-only meetings). Still mark complete.
        inv = bot_invitations.find_by_meeting(platform, native_id)
        if inv:
            bot_invitations.update_status(inv["id"], "completed", completed=True)
        return {"status": "empty_transcript", "session_id": native_id}

    # 4. Translate to canonical → Session.
    source = os.environ.get("CONCLAVE_INGEST_SOURCE", "recato")
    canonical = to_canonical(vexa, source=source)

    # Reuse the canonical→Session build path.
    from api.transcripts_routes import _build_and_save_session
    from transcripts import store as transcripts_store

    # 5. Idempotency: same external_id ⇒ same session_id ⇒ load returns it.
    existing = transcripts_store.load_session(canonical["meeting"]["external_id"])
    if existing is not None:
        session_id = existing.session_id
        status_label = "duplicate"
    else:
        session = _build_and_save_session(canonical)
        session_id = session.session_id
        status_label = "accepted"

    # 6. Bind to workspace/owner via the bot_invitation we created in 2.1.
    inv = bot_invitations.find_by_meeting(platform, native_id)
    if inv is not None:
        transcripts_store.set_workspace(
            session_id=session_id,
            workspace_id=inv["workspace_id"],
            owner_user_id=inv["user_id"],
            visibility="owner-only",
        )
        bot_invitations.update_status(inv["id"], "completed", completed=True)
    else:
        logger.warning(
            "no bot_invitation found for %s/%s — session lands without "
            "workspace binding (likely a Recato-originated meeting we didn't launch)",
            platform,
            native_id,
        )

    # 7. Enrichment kicks asynchronously (mirrors /transcripts/ingest).
    if status_label == "accepted":
        from api.transcripts_routes import _enrich_in_background
        asyncio.create_task(asyncio.to_thread(_enrich_in_background, session_id))

    return {"session_id": session_id, "status": status_label}
