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

    try:
        recato_resp = launch_bot(
            platform="google_meet",
            native_meeting_id=meet_code,
            bot_name=DEFAULT_BOT_NAME,
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


class AddShareBody(BaseModel):
    email: EmailStr


@router.post("/{session_id}/shares", status_code=201)
def add_share(
    session_id: str,
    body: AddShareBody,
    user: dict = Depends(require_current_user),
):
    """Owner adds an attendee to an existing meeting.

    Phase 2.13 — the post-fact share path. After-enrichment email send
    (2.8) will pick this up when wired.
    """
    # Only the inviter can add shares in v1. Workspace-level admin lives in v1.5.
    inv = bot_invitations.find_by_meeting("google_meet", session_id)
    if inv is None or inv["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Meeting not found")

    from infra.workspaces import add_meeting_share
    add_meeting_share(session_id, str(body.email), user["id"])
    return {"ok": True, "email": str(body.email)}
