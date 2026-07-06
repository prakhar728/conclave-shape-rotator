"""Recato `meeting.completed` webhook receiver.

Mounted at POST /api/webhooks/capture/meeting-completed. Replaces the
separate `connectors.capture.consumer` service for the v1 hosted product
(BUILD_DOC §10.5). The standalone consumer.py stays for users running
Recato as a third-party producer; ours is the in-process path.

Flow:
  1. Verify Recato's HMAC signature (`X-Signature: sha256=<hex>`,
     `CAPTURE_WEBHOOK_SECRET` env var). Optional for dev — when the secret
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

from connectors.capture.translator import to_canonical
from infra import bot_invitations

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks/capture", tags=["webhooks"])


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


def _set_store_audio_meta(session_id: str, store_audio: bool) -> None:
    """Record the per-meeting store-audio decision on the session metadata (Task #30).

    Read-side signal only — the actual store/no-store enforcement happened at the
    audio-chunk write. Best-effort: a metadata write hiccup must not block finalize."""
    from transcripts import store as transcripts_store
    try:
        sess = transcripts_store.load_session(session_id)
        if sess is not None:
            sess.metadata.store_audio = store_audio
            transcripts_store.set_metadata(session_id, sess.metadata)
    except Exception:  # noqa: BLE001
        logger.exception("webhook: set store_audio failed for %s", session_id)


@router.post("/meeting-completed", status_code=status.HTTP_202_ACCEPTED)
async def on_meeting_completed(
    request: Request,
    payload: _MeetingCompletedEvent,
    x_signature: Optional[str] = Header(default=None, alias="X-Signature"),
) -> dict:
    """Finalize: live buffer → translate → bind to workspace → enrich (P1; no fetch)."""
    # 1. Auth.
    secret = os.environ.get("CAPTURE_WEBHOOK_SECRET")
    if secret:
        raw = await request.body()
        if not _verify(raw, x_signature, secret):
            raise HTTPException(status_code=401, detail="signature mismatch")
    else:
        logger.warning(
            "CAPTURE_WEBHOOK_SECRET not set — accepting unsigned webhook (dev only)"
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

    # 3-5. Finalize from the live buffer. Segments streamed in during the meeting
    # via the capture consumer (P1), so this webhook is FINALIZE-ONLY — no post-hoc
    # fetch from Recato. `raw_diarization` is materialized from `live_segments`
    # exactly once here (preserving its write-once invariant), then the buffer is
    # cleared. (`_fetch_recato_transcript` is now unused — kept for the legacy/
    # external-producer path.)
    from api.transcripts_routes import _build_and_save_session
    from transcripts import store as transcripts_store

    existing = transcripts_store.load_session(native_id)
    if existing is not None:
        # Idempotent: this meeting was already materialized.
        session_id = existing.session_id
        status_label = "duplicate"
        transcripts_store.clear_live_segments(native_id)
    else:
        buffered = transcripts_store.live_segments(native_id)
        if not buffered:
            # Silence-only / nothing streamed. Still mark the invitation complete.
            inv = bot_invitations.find_by_meeting(platform, native_id)
            if inv:
                bot_invitations.update_status(inv["id"], "completed", completed=True)
            return {"status": "empty_transcript", "session_id": native_id}
        source = os.environ.get("CONCLAVE_INGEST_SOURCE", "capture")
        canonical = to_canonical(
            {"native_meeting_id": native_id, "platform": platform, "segments": buffered},
            source=source,
        )
        session = _build_and_save_session(canonical)
        session_id = session.session_id
        status_label = "accepted"
        transcripts_store.clear_live_segments(native_id)

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
        # Manual invite "focus/intent" → enrichment grounding. Set BEFORE the
        # calendar fill in 6b so a manual intent wins over the calendar agenda.
        if status_label == "accepted" and inv.get("intent"):
            try:
                sess = transcripts_store.load_session(session_id)
                if sess is not None:
                    sess.metadata.raw_intent = inv["intent"]
                    transcripts_store.set_metadata(session_id, sess.metadata)
            except Exception:  # noqa: BLE001 — intent is optional grounding
                logger.exception("webhook: set raw_intent failed for %s", session_id)
        # Task #30: record the gMeet store-audio decision on the session so the UI
        # knows whether a player should appear. Enforcement already happened at the
        # write; this is the read-side signal.
        if status_label == "accepted" and inv.get("store_audio") is not None:
            _set_store_audio_meta(session_id, bool(inv["store_audio"]))
    else:
        # In-person meetings have no bot_invitation, but capture sends the workspace in the payload —
        # bind the session to it so the transcript is visible in the workspace + identity can resolve.
        # Best-effort: a bad/non-existent workspace (e.g. a dev label) must NOT 500 the finalize (the FK
        # to `workspaces` would otherwise raise). In production the record UI passes a real workspace_id.
        payload_ws = meeting.get("workspace_id")
        if payload_ws:
            try:
                # In-person has no inviter → default ownership to the workspace creator so they can
                # manage/TAG the meeting (tagging is owner-gated; a NULL owner makes it un-taggable).
                from infra.workspaces import get_workspace
                ws_row = get_workspace(payload_ws)
                owner = ws_row.get("created_by") if ws_row else None
                transcripts_store.set_workspace(
                    session_id=session_id,
                    workspace_id=payload_ws,
                    owner_user_id=owner,          # workspace creator owns walk-up recordings
                    # Task #32 §0b-D: OWNER-PRIVATE by default — bare membership no longer
                    # auto-exposes a meeting. The owner opts in via "share to workspace".
                    visibility="owner-only",
                )
                _wf = transcripts_store.get_workspace_fields(session_id)
                logger.info("in-person bind: session=%s payload_ws=%r ws_exists=%s → stored_ws=%r",
                            session_id, payload_ws, bool(ws_row), (_wf or {}).get("workspace_id"))
            except Exception:  # noqa: BLE001 — never block finalize on a bad workspace binding
                logger.warning("in-person workspace bind to %r failed for %s — session unbound",
                               payload_ws, native_id)
        else:
            logger.warning(
                "no bot_invitation and no payload workspace for %s/%s — session lands unbound",
                platform, native_id,
            )
        # Task #30: in-person store-audio decision rides the webhook payload (capture
        # forwards the WS-connect toggle). Record it for the read-side UI signal.
        if status_label == "accepted" and meeting.get("store_audio") is not None:
            _set_store_audio_meta(session_id, bool(meeting.get("store_audio")))

        # Task #12: in-person agenda → enrichment grounding. The record modal stashed
        # the agenda keyed by the meeting uid (== native_id); apply it as raw_intent
        # so the in-person summary is grounded just like online/upload. MUST run here,
        # BEFORE enrich is enqueued below — once set, it flows through the existing
        # compile_intent → <meeting_intent> chain (no raw-text splice). Manual-intent-
        # wins: never overwrite an already-set raw_intent. Best-effort — a stash hiccup
        # must not block finalize. Only on a fresh session ("accepted"), never a
        # duplicate (already enriched, and pop_agenda would consume nothing useful).
        if status_label == "accepted":
            try:
                from infra import inperson_agenda
                agenda = inperson_agenda.pop_agenda(native_id)
                if agenda:
                    sess = transcripts_store.load_session(session_id)
                    if sess is not None and not (
                        sess.metadata.raw_intent and sess.metadata.raw_intent.strip()
                    ):
                        sess.metadata.raw_intent = agenda
                        transcripts_store.set_metadata(session_id, sess.metadata)
            except Exception:  # noqa: BLE001 — agenda is optional grounding
                logger.exception("webhook: set in-person agenda intent failed for %s",
                                 session_id)

    # Task #32: stamp the RECORDER on the session (the identify host_user), for BOTH ingress
    # modes. In-person recorders are stashed at record-start by uid (== native_id); gMeet's
    # "recorder" is the inviter. None → identify falls back to the workspace owner. MUST run
    # before the identity task below so `meeting_host_email` reads it. Best-effort.
    if status_label == "accepted":
        try:
            from infra import inperson_recorder
            recorder = inperson_recorder.pop_recorder(native_id)
            if recorder is None and inv is not None:
                recorder = inv["user_id"]
            if recorder:
                transcripts_store.set_recorder(session_id, recorder)
        except Exception:  # noqa: BLE001 — recorder is best-effort (owner is the fallback)
            logger.exception("webhook: set recorder for %s failed", session_id)

    # 6b. Calendar enrichment (best-effort): if this Meet was auto-recorded
    # from a calendar event, link the transcript to the event and auto-share
    # it with the event's attendees. Never fatal — a failure here must not
    # block transcript ingest.
    if platform == "google_meet":
        try:
            from infra.meeting_calendar_links import link_completed_meeting
            link_completed_meeting(
                meet_code=native_id,
                session_id=session_id,
                inviter_user_id=inv["user_id"] if inv else None,
            )
        except Exception:  # noqa: BLE001
            logger.exception("calendar link failed for %s", native_id)

    # 7. Post-meeting identity (P4) THEN enrichment, async. Identity first so
    # resolved_speakers carries voiceprint_ids before enrichment + the read path.
    if status_label == "accepted":
        from api.transcripts_routes import _enrich_in_background
        from connectors.capture.identify import identify_meeting
        # In-person meetings have no bot_invitation → fall back to the workspace carried in the webhook
        # payload (capture sends it). Online still prefers the invitation's workspace.
        ws_for_identity = (inv["workspace_id"] if inv else None) or meeting.get("workspace_id")

        async def _identify_then_enrich():
            # Task #16: identify_meeting SUBMITS a durable diarize job when the queue is on and returns
            # True ("deferred") — a DiariZen worker runs the engine and POSTs /api/diarize/result, which
            # reconciles identity THEN chains enrichment (preserving the identity-before-enrich order).
            # When it runs inline (blocking/legacy path) it returns False and we enrich here as before.
            deferred = False
            try:
                deferred = await identify_meeting(session_id, native_id, ws_for_identity)
            except Exception:  # noqa: BLE001 — identity is best-effort
                logger.exception("post-meeting identity failed for %s", session_id)
            if not deferred:
                await asyncio.to_thread(_enrich_in_background, session_id)

        asyncio.create_task(_identify_then_enrich())

    return {"session_id": session_id, "status": status_label}
