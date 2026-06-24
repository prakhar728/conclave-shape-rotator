"""Bot invitation HTTP surface — paste a Meet link, launch the bot.

All routes are gated by `auth.session.require_current_user`. Conclave's
backend holds the single shared Recato API token (BUILD_DOC §4 D-shared-bot)
so the end-user's browser never touches Recato directly.

Endpoints:
- POST /api/meetings/invite-bot  { meet_url_or_code, workspace_id, attendee_emails? }
- GET  /api/meetings/{session_id}/bot-status
- POST /api/meetings/{session_id}/shares
"""
from __future__ import annotations

import logging
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

logger = logging.getLogger(__name__)

from auth.session import require_current_user
from connectors.recato.launch import (
    DEFAULT_BOT_NAME,
    RecatoLaunchError,
    launch_bot,
    parse_meet_input,
    stop_bot,
)
from infra import bot_invitations, dispatcher, workspaces

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


class InviteBotBody(BaseModel):
    meet_url_or_code: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    attendee_emails: Optional[List[EmailStr]] = None
    # Optional freeform "focus / what to capture" — grounds enrichment
    # (transcripts/compile_intent.py) for meetings with no calendar event.
    intent: Optional[str] = Field(default=None, max_length=4000)


def _require_workspace_member(workspace_id: str, user_id: str) -> dict:
    ws = workspaces.get_workspace(workspace_id)
    if ws is None or not workspaces.is_member(workspace_id, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.post("/invite-bot", status_code=201)
def invite_bot(
    body: InviteBotBody,
    user: dict = Depends(require_current_user),
):
    """Launch the Conclave bot for a Google Meet.

    The session_id we return matches Recato's `meeting.external_id` so the
    eventual meeting.completed webhook can dedup against the existing
    `transcript_sessions` row.
    """
    _require_workspace_member(body.workspace_id, user["id"])

    try:
        meet_code = parse_meet_input(body.meet_url_or_code)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))

    # P1: Conclave owns meeting concurrency now (was Recato's per-token limit).
    # Enforce per-workspace + global caps and pick the warmed capture account
    # BEFORE creating the row, so the cap math doesn't count this attempt.
    try:
        account_id = dispatcher.check_and_assign(body.workspace_id)
    except dispatcher.CapacityError as e:
        raise HTTPException(status_code=429, detail=str(e))

    # Create the invitation row BEFORE launching so even a failed launch
    # leaves an audit trail the user can see in /bot-status.
    invitation = bot_invitations.create_invitation(
        user_id=user["id"],
        workspace_id=body.workspace_id,
        platform="google_meet",
        native_meeting_id=meet_code,
        bot_name=DEFAULT_BOT_NAME,
        status="requested",
        intent=body.intent,
        assigned_account_id=account_id,
    )

    # Per-meeting webhook URL points at our 2.4 receiver. Preferred over
    # Recato's global POST_MEETING_HOOKS env var so each launch can carry
    # its own callback (and so Recato doesn't have to be reconfigured
    # globally for every deploy environment).
    import os as _os
    webhook_url = _os.environ.get("RECATO_MEETING_COMPLETED_URL")

    try:
        recato_resp = launch_bot(
            platform="google_meet",
            native_meeting_id=meet_code,
            bot_name=DEFAULT_BOT_NAME,
            webhook_url=webhook_url,
            user_id=account_id,
        )
    except RecatoLaunchError as e:
        bot_invitations.update_status(invitation["id"], "failed", completed=True)
        raise HTTPException(status_code=502, detail=str(e))

    recato_bot_id = (
        recato_resp.get("id")
        if isinstance(recato_resp, dict) and isinstance(recato_resp.get("id"), int)
        else None
    )
    bot_invitations.update_status(
        invitation["id"], "joining", recato_bot_id=recato_bot_id
    )

    # Persist attendee shares now so the post-enrichment email blast (2.8)
    # has them ready to consume.
    if body.attendee_emails:
        from infra.workspaces import add_meeting_share
        for email in body.attendee_emails:
            add_meeting_share(meet_code, str(email), user["id"])

    return {
        "invitation_id": invitation["id"],
        "meeting_session_id": meet_code,
        "status": "joining",
    }


@router.post("/bot/status_change")
def bot_status_change(payload: dict):
    """Receiver for the capture bot's lifecycle callbacks (machine -> Conclave).

    The bot POSTs {connection_id, status, reason, completion_reason, ...} on each
    transition (requested -> joining -> awaiting_admission -> active -> completed/
    failed). `connection_id` is the native meet code. We map the bot status onto the
    bot_invitation so the dashboard reflects reality instead of sitting on "joining".

    Unauthenticated machine callback (the bot holds no user token). The bot reaches
    this via BOT_CONFIG.meetingApiCallbackUrl (= CONCLAVE_CALLBACK_URL). ⚠️ prod should
    gate this with a shared secret; local is open.
    """
    data = payload or {}
    connection_id = data.get("connection_id")
    status = data.get("status")
    if not connection_id or not status:
        return {"ok": False, "reason": "missing connection_id/status"}

    inv = bot_invitations.find_by_meeting("google_meet", connection_id)
    if inv is None:
        return {"ok": False, "reason": "no invitation"}
    if inv["status"] in ("completed", "failed"):
        return {"ok": True, "note": "already terminal"}

    reason = (data.get("reason") or data.get("completion_reason") or "").lower()
    if status == "active":
        new, terminal = "active", False
    elif status in ("joining", "awaiting_admission", "requested"):
        new, terminal = "joining", False
    elif status == "failed" or status.startswith("awaiting_admission_"):
        new, terminal = "failed", True
    elif status == "completed":
        # Rejections/timeouts arrive as completed+reason; surface them as failed.
        bad = any(k in reason for k in ("reject", "timeout", "admission", "denied"))
        new, terminal = ("failed", True) if bad else ("completed", True)
    else:
        return {"ok": True, "ignored": status}

    bot_invitations.update_status(inv["id"], new, completed=terminal)
    logger.info(
        "bot status_change: %s -> %s (bot status=%s reason=%r)",
        connection_id, new, status, reason,
    )
    return {"ok": True, "status": new}


@router.get("/active")
def list_active_invitations(user: dict = Depends(require_current_user)):
    """List the current user's non-terminal bot invitations.

    The dashboard's "Live now" section surfaces these so the user can see
    everything currently transcribing (and stop it if needed) without
    needing to remember which tab they invited from.
    """
    from storage.sqlite import _get_conn
    rows = _get_conn().execute(
        "SELECT id, native_meeting_id, platform, status, bot_name, "
        "recato_bot_id, created_at "
        "FROM bot_invitations "
        "WHERE user_id = ? AND status NOT IN ('completed', 'failed') "
        "ORDER BY created_at DESC",
        (user["id"],),
    ).fetchall()
    return {
        "active": [
            {
                "invitation_id": r["id"],
                "session_id": r["native_meeting_id"],
                "platform": r["platform"],
                "status": r["status"],
                "bot_name": r["bot_name"],
                "recato_bot_id": r["recato_bot_id"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


@router.delete("/{session_id}/bot")
def stop_bot_route(
    session_id: str,
    user: dict = Depends(require_current_user),
):
    """Stop the Conclave bot mid-meeting (or mid-stuck-state).

    Authorizes against the bot_invitation (only the inviter can stop).
    Calls Recato's DELETE /bots/{platform}/{id} which triggers Recato's
    own meeting-completion flow — the same webhook path fires as if the
    user had kicked the bot from Meet UI, so no special ingest plumbing
    is needed here.
    """
    inv = bot_invitations.find_by_meeting("google_meet", session_id)
    if inv is None or inv["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="No invitation for this meeting")
    if inv["status"] in ("completed", "failed"):
        return {"ok": True, "status": inv["status"], "note": "already terminal"}

    try:
        stop_bot(platform="google_meet", native_meeting_id=session_id)
    except RecatoLaunchError as e:
        # Even if Recato can't be reached, mark the invitation as failed
        # so the user isn't stuck looking at a forever-joining state.
        bot_invitations.update_status(inv["id"], "failed", completed=True)
        raise HTTPException(status_code=502, detail=str(e))

    # IMPORTANT: Recato does NOT fire `meeting.completed` for bots stopped
    # via DELETE /bots — only for naturally-ended meetings. Without explicit
    # ingest here, the transcript Recato captured would never reach Conclave
    # (verified empirically with bot 20 — 3 segments on Recato side, zero
    # session rows in Conclave). So we do the same fetch+translate+save the
    # webhook handler does, inline.
    try:
        _ingest_from_recato_now(session_id, inviter_user_id=user["id"],
                                workspace_id=inv["workspace_id"])
    except Exception:  # noqa: BLE001 — best-effort; don't block the stop UX
        logger.exception("post-stop ingest failed for %s", session_id)

    bot_invitations.update_status(inv["id"], "completed", completed=True)
    return {"ok": True, "status": "completed"}


def _ingest_from_recato_now(
    session_id: str,
    *,
    inviter_user_id: str,
    workspace_id: str,
) -> None:
    """Mirror the webhook receiver's fetch+translate+save path, but
    triggered locally when the user clicks Stop. Recato doesn't fire
    `meeting.completed` for API-deleted bots, so this is how we close
    the loop in that case.

    NOTE: we retry the transcript fetch a few times with delay because
    Recato's stop_bot API returns before the bot subprocess has finished
    flushing its final segments. Without retries, we'd fetch an empty
    transcript and bail. Empirical: takes ~3-6 seconds post-stop for the
    transcript to be complete on Recato's side."""
    import os, threading, time

    from connectors.recato.translator import to_canonical
    from transcripts import store as transcripts_store

    # Finalize from `live_segments` — the buffer the capture consumer streamed into
    # during the meeting (P1). This MIRRORS the webhook finalize path; we no longer
    # HTTP-fetch from Recato (that endpoint is gone in the capture rebuild). stop_bot
    # returns before the bot flushes its final segments + the consumer ingests them,
    # so retry a few times over ~12s.
    buffered = []
    for attempt in range(6):
        buffered = transcripts_store.live_segments(session_id)
        if buffered:
            logger.info(
                "post-stop ingest: %d live segments for %s (attempt %d)",
                len(buffered), session_id, attempt,
            )
            break
        logger.info(
            "post-stop ingest: 0 live segments for %s, retrying (attempt %d)",
            session_id, attempt,
        )
        time.sleep(2)

    if not buffered:
        logger.warning(
            "post-stop ingest: gave up — no live segments for %s", session_id,
        )
        return

    source = os.environ.get("CONCLAVE_INGEST_SOURCE", "capture")
    canonical = to_canonical(
        {"native_meeting_id": session_id, "platform": "google_meet", "segments": buffered},
        source=source,
    )

    existing = transcripts_store.load_session(canonical["meeting"]["external_id"])
    if existing is None:
        from api.transcripts_routes import _build_and_save_session, _enrich_in_background
        sess = _build_and_save_session(canonical)
        stored_session_id = sess.session_id
        transcripts_store.set_workspace(
            session_id=sess.session_id,
            workspace_id=workspace_id,
            owner_user_id=inviter_user_id,
            visibility="owner-only",
        )
        # Carry the manual invite "focus/intent" onto the session so enrichment
        # can ground on it (set before enrichment kicks below).
        try:
            inv = bot_invitations.find_by_meeting("google_meet", session_id)
            if inv and inv.get("intent"):
                sess.metadata.raw_intent = inv["intent"]
                transcripts_store.set_metadata(sess.session_id, sess.metadata)
        except Exception:  # noqa: BLE001 — intent is optional grounding
            logger.exception("post-stop ingest: set raw_intent failed for %s", sess.session_id)
        logger.info("post-stop ingest: saved + bound %s, kicking enrichment", sess.session_id)
        # Sync context (the route isn't async), so use a plain thread.
        # _enrich_in_background is itself sync; the webhook handler wraps it
        # in asyncio.to_thread only because that handler is async.
        threading.Thread(
            target=_enrich_in_background, args=(sess.session_id,), daemon=True
        ).start()
    else:
        # Already exists (e.g. webhook beat us). Just ensure workspace bind.
        stored_session_id = existing.session_id
        transcripts_store.set_workspace(
            session_id=existing.session_id,
            workspace_id=workspace_id,
            owner_user_id=inviter_user_id,
            visibility="owner-only",
        )
        logger.info("post-stop ingest: existing session %s — re-bound workspace", existing.session_id)

    # Calendar enrichment (best-effort): mirror the webhook's step 6b so a
    # bot stopped by hand gets the same transcript↔event link + attendee
    # auto-share as a naturally-ended meeting. `session_id` here is the Meet
    # code (native_meeting_id). Never fatal to the stop UX.
    try:
        from infra.meeting_calendar_links import link_completed_meeting
        link_completed_meeting(
            meet_code=session_id,
            session_id=stored_session_id,
            inviter_user_id=inviter_user_id,
        )
    except Exception:  # noqa: BLE001
        logger.exception("post-stop ingest: calendar link failed for %s", session_id)


@router.get("/{session_id}/bot-status")
def bot_status(
    session_id: str,
    user: dict = Depends(require_current_user),
):
    """Poll the bot's current status. 404 if no invitation has been issued for this meet."""
    inv = bot_invitations.find_by_meeting("google_meet", session_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="No invitation for this meeting")
    # Authz: only the inviter (or a workspace member) can poll. v1 only checks
    # the inviter; the workspace-scoped variant lives in 1.5+ multi-member.
    if inv["user_id"] != user["id"] and not workspaces.is_member(
        inv["workspace_id"], user["id"]
    ):
        raise HTTPException(status_code=404, detail="No invitation for this meeting")
    return {
        "invitation_id": inv["id"],
        "status": inv["status"],
        "recato_bot_id": inv["recato_bot_id"],
        "created_at": inv["created_at"],
        "completed_at": inv["completed_at"],
    }


class VisibilityBody(BaseModel):
    visibility: str  # 'owner-only' | 'shared'


_OWNER_TOGGLE_VISIBILITY = {"owner-only", "shared"}


@router.post("/{session_id}/visibility")
def set_visibility(
    session_id: str,
    body: VisibilityBody,
    user: dict = Depends(require_current_user),
):
    """Owner-only — toggle a meeting between owner-only and shared.

    'workspace' and 'public-link' aren't UI-exposed in v1 (BUILD_DOC §11);
    the route rejects them so accidental clients can't escalate visibility.
    """
    if body.visibility not in _OWNER_TOGGLE_VISIBILITY:
        raise HTTPException(
            status_code=422,
            detail="visibility must be 'owner-only' or 'shared'",
        )
    # Authorize: only the meeting's owner can flip visibility.
    from transcripts import store as _store
    fields = _store.get_workspace_fields(session_id)
    if not fields or fields.get("owner_user_id") != user["id"]:
        raise HTTPException(status_code=404, detail="Meeting not found")
    _store.set_workspace(
        session_id=session_id,
        workspace_id=fields["workspace_id"],
        owner_user_id=fields["owner_user_id"],
        visibility=body.visibility,
    )
    return {"ok": True, "visibility": body.visibility}


class AddShareBody(BaseModel):
    email: EmailStr
    # 'summary_and_transcript' (default) lets the recipient open the raw
    # transcript; 'summary_only' withholds it. Validated against the
    # canonical list in infra.workspaces (CHECK constraint backs it in SQL).
    scope: str = "summary_and_transcript"


def _user_owns_meeting(session_id: str, user_id: str) -> bool:
    """True if the user owns this meeting via the transcript_session row
    (post-completion case) OR via a bot_invitation (pre-completion case,
    no webhook yet)."""
    from transcripts import store as _store
    fields = _store.get_workspace_fields(session_id)
    if fields and fields.get("owner_user_id") == user_id:
        return True
    inv = bot_invitations.find_by_meeting("google_meet", session_id)
    if inv is not None and inv["user_id"] == user_id:
        return True
    return False


@router.get("/{session_id}/shares")
def list_shares(
    session_id: str,
    user: dict = Depends(require_current_user),
):
    """Owner-only — list attendees explicitly shared on this meeting."""
    if not _user_owns_meeting(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="Meeting not found")
    from infra.workspaces import list_meeting_shares
    shares = list_meeting_shares(session_id)
    return {
        "shares": [
            {
                "email": s["user_email"],
                "granted_at": s["granted_at"],
                "scope": s.get("scope") or "summary_and_transcript",
            }
            for s in shares
        ]
    }


@router.post("/{session_id}/shares", status_code=201)
def add_share(
    session_id: str,
    body: AddShareBody,
    user: dict = Depends(require_current_user),
):
    """Owner adds an attendee to a meeting they own.

    Phase 2.13 — the post-fact share path. Authorizes via either
    `transcript_sessions.owner_user_id` (post-completion) or
    `bot_invitations.user_id` (pre-completion, before the webhook fires).
    Email send happens on the next enrichment run (2.8 reads
    meeting_shares fresh each time); live per-share email is a v1.5 polish.
    """
    if not _user_owns_meeting(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="Meeting not found")

    from infra.workspaces import SHARE_SCOPES, add_meeting_share
    if body.scope not in SHARE_SCOPES:
        raise HTTPException(
            status_code=422,
            detail=f"scope must be one of {list(SHARE_SCOPES)}",
        )
    add_meeting_share(session_id, str(body.email), user["id"], scope=body.scope)
    return {"ok": True, "email": str(body.email), "scope": body.scope}


class RetentionBody(BaseModel):
    # 'inherit' clears the override (use the account default); 'keep_forever'
    # pins this meeting; 'days' auto-deletes its raw transcript after `days`.
    mode: Literal["inherit", "keep_forever", "days"]
    days: Optional[int] = None


@router.post("/{session_id}/retention")
def set_meeting_retention(
    session_id: str,
    body: RetentionBody,
    user: dict = Depends(require_current_user),
):
    """Owner sets the per-meeting retention override (Transcript Saving P2).

    Stored on the transcript_sessions row, so it only applies once the meeting
    has been processed into a session — a not-yet-completed meeting returns 409.
    """
    if not _user_owns_meeting(session_id, user["id"]):
        raise HTTPException(status_code=404, detail="Meeting not found")

    if body.mode == "days":
        if body.days is None or body.days <= 0:
            raise HTTPException(
                status_code=422, detail="days must be a positive integer"
            )
        override: Optional[str] = str(body.days)
    elif body.mode == "keep_forever":
        override = "keep_forever"
    else:  # inherit
        override = None

    from transcripts import store as _store
    if _store.get_workspace_fields(session_id) is None:
        raise HTTPException(
            status_code=409,
            detail="Retention can be set once the meeting has been processed",
        )
    _store.set_retention_override(session_id, override)
    return {"ok": True, "retention_override": override}


class TagSpeakerBody(BaseModel):
    speaker_label: str = Field(min_length=1)
    name: str = Field(min_length=1)
    email: Optional[EmailStr] = None


@router.post("/{session_id}/tag-speaker")
async def tag_speaker(
    session_id: str,
    body: TagSpeakerBody,
    user: dict = Depends(require_current_user),
):
    """Name a speaker in a meeting (P4 manual tag — the two locked propagations).

    (a) Update THIS transcript's display overlay instantly
        (`resolved_speakers[label].name`; `raw_diarization` is never mutated), and
    (b) if the speaker carries an FPM voiceprint, push the name to FPM so FUTURE
        meetings auto-recognize them (`/v1/knowledge` → `store.set_name`). The FPM
        push is best-effort — the local overlay always applies.

    ASSUMPTION (verify at runtime): the voiceprint_id lands on
    `resolved_speakers[label]` once the live/post diarize-identify wiring populates
    it. Until then (no voiceprint_id) only the display overlay applies — which is
    the correct degenerate behavior for diarization-only labels.
    """
    from transcripts import store as _store
    from infra import fpm_consent

    session = _store.load_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session {session_id!r} not found")
    wf = _store.get_workspace_fields(session_id) or {}
    owner = wf.get("owner_user_id")
    if owner and owner != user["id"]:
        raise HTTPException(status_code=403, detail="only the meeting owner can tag speakers")

    # (a) display overlay — instant; raw_diarization untouched.
    resolved = dict(session.metadata.resolved_speakers or {})
    entry = dict(resolved.get(body.speaker_label) or {})
    entry["name"] = body.name
    if body.email:
        entry["email"] = str(body.email)
    resolved[body.speaker_label] = entry
    md = session.metadata.model_copy(update={"resolved_speakers": resolved})
    _store.set_metadata(session_id, md)

    # (b) cross-meeting persistence — only when the label carries an FPM voiceprint.
    voiceprint_id = entry.get("voiceprint_id")
    workspace_id = wf.get("workspace_id")
    fpm_result = None
    if voiceprint_id and workspace_id:
        binding = {"voiceprint_id": voiceprint_id, "name": body.name}
        if body.email:
            binding["email"] = str(body.email)
        try:
            fpm_result = await fpm_consent.push_knowledge(workspace_id, [binding])
        except HTTPException as e:  # best-effort — overlay already applied
            logger.warning("tag-speaker: FPM push failed for %s: %s", session_id, e.detail)

    return {
        "status": "tagged",
        "speaker_label": body.speaker_label,
        "name": body.name,
        "voiceprint_pushed": bool(voiceprint_id and workspace_id),
        "fpm": fpm_result,
    }
