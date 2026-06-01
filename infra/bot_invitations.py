"""CRUD over the `bot_invitations` table (Alembic 0002).

Tracks each "Conclave user invited the bot to a Meet" event:
- Provenance: which user fired the invite, in which workspace
- Recato handle: `recato_bot_id` for status polling
- Status machine: requested → joining → active → completed | failed

The webhook receiver (Phase 2.4) advances `status` to 'completed' when
Recato fires `meeting.completed`. The bot-status polling endpoint reads
the same row.
"""
from __future__ import annotations

import secrets
from typing import Optional

from storage.sqlite import _get_conn, _now

VALID_STATUSES = {"requested", "joining", "active", "completed", "failed"}


def _new_invitation_id() -> str:
    return f"inv_{secrets.token_hex(4)}"


def create_invitation(
    *,
    user_id: str,
    workspace_id: str,
    platform: str,
    native_meeting_id: str,
    bot_name: str = "Conclave",
    recato_bot_id: Optional[int] = None,
    status: str = "requested",
) -> dict:
    """Insert a new row. Returns the inserted dict."""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    inv_id = _new_invitation_id()
    now = _now()
    _get_conn().execute(
        "INSERT INTO bot_invitations "
        "(id, user_id, workspace_id, platform, native_meeting_id, recato_bot_id, "
        " status, bot_name, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (inv_id, user_id, workspace_id, platform, native_meeting_id,
         recato_bot_id, status, bot_name, now),
    )
    return {
        "id": inv_id,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "platform": platform,
        "native_meeting_id": native_meeting_id,
        "recato_bot_id": recato_bot_id,
        "status": status,
        "bot_name": bot_name,
        "created_at": now,
        "completed_at": None,
    }


def get_invitation(invitation_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT id, user_id, workspace_id, platform, native_meeting_id, "
        "recato_bot_id, status, bot_name, created_at, completed_at "
        "FROM bot_invitations WHERE id = ?",
        (invitation_id,),
    ).fetchone()
    return dict(row) if row else None


def find_by_meeting(platform: str, native_meeting_id: str) -> Optional[dict]:
    """Look up the most recent invitation for a given Meet code."""
    row = _get_conn().execute(
        "SELECT id, user_id, workspace_id, platform, native_meeting_id, "
        "recato_bot_id, status, bot_name, created_at, completed_at "
        "FROM bot_invitations WHERE platform = ? AND native_meeting_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (platform, native_meeting_id),
    ).fetchone()
    return dict(row) if row else None


def update_status(
    invitation_id: str,
    status: str,
    *,
    recato_bot_id: Optional[int] = None,
    completed: bool = False,
) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    fields: list[str] = ["status = ?"]
    params: list = [status]
    if recato_bot_id is not None:
        fields.append("recato_bot_id = ?")
        params.append(recato_bot_id)
    if completed:
        fields.append("completed_at = ?")
        params.append(_now())
    params.append(invitation_id)
    _get_conn().execute(
        f"UPDATE bot_invitations SET {', '.join(fields)} WHERE id = ?",
        tuple(params),
    )
