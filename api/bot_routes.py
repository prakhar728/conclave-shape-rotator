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

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from auth.session import require_current_user
from connectors.recato.launch import (
    DEFAULT_BOT_NAME,
    RecatoLaunchError,
    launch_bot,
    parse_meet_input,
    stop_bot,
)
from infra import bot_invitations, workspaces

router = APIRouter(prefix="/api/meetings", tags=["meetings"])


class InviteBotBody(BaseModel):
    meet_url_or_code: str = Field(min_length=1)
    workspace_id: str = Field(min_length=1)
    attendee_emails: Optional[List[EmailStr]] = None


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

    # Create the invitation row BEFORE calling Recato so even a failed launch
    # leaves an audit trail the user can see in /bot-status.
    invitation = bot_invitations.create_invitation(
        user_id=user["id"],
        workspace_id=body.workspace_id,
        platform="google_meet",
        native_meeting_id=meet_code,
        bot_name=DEFAULT_BOT_NAME,
        status="requested",
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

    # Optimistic local flip — Recato should fire the webhook moments later,
    # which would also flip this; whichever lands first is fine.
    bot_invitations.update_status(inv["id"], "completed", completed=True)
    return {"ok": True, "status": "completed"}


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
            {"email": s["user_email"], "granted_at": s["granted_at"]}
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

    from infra.workspaces import add_meeting_share
    add_meeting_share(session_id, str(body.email), user["id"])
    return {"ok": True, "email": str(body.email)}
