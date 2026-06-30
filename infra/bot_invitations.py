"""CRUD over the `bot_invitations` table (Alembic 0002).

Tracks each "Conclave user invited the bot to a Meet" event:
- Provenance: which user fired the invite, in which workspace
- Recato handle: `capture_bot_id` for status polling
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
    capture_bot_id: Optional[int] = None,
    status: str = "requested",
    intent: Optional[str] = None,
    assigned_account_id: Optional[str] = None,
    store_audio: Optional[bool] = None,
) -> dict:
    """Insert a new row. Returns the inserted dict.

    ``intent`` is the optional freeform "focus / what to capture" the user
    supplied at invite time — carried to the session at ingest and compiled
    into enrichment grounding (transcripts/compile_intent.py).

    ``store_audio`` (Task #30) is the per-meeting store/no-store decision for the
    gMeet path, resolved against the workspace default at invite time. None = the
    audio write defaults to keep (back-compat)."""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    inv_id = _new_invitation_id()
    now = _now()
    _get_conn().execute(
        "INSERT INTO bot_invitations "
        "(id, user_id, workspace_id, platform, native_meeting_id, capture_bot_id, "
        " status, bot_name, intent, assigned_account_id, store_audio, created_at, completed_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (inv_id, user_id, workspace_id, platform, native_meeting_id,
         capture_bot_id, status, bot_name, intent, assigned_account_id,
         None if store_audio is None else int(store_audio), now),
    )
    return {
        "id": inv_id,
        "user_id": user_id,
        "workspace_id": workspace_id,
        "platform": platform,
        "native_meeting_id": native_meeting_id,
        "capture_bot_id": capture_bot_id,
        "status": status,
        "bot_name": bot_name,
        "intent": intent,
        "assigned_account_id": assigned_account_id,
        "store_audio": store_audio,
        "created_at": now,
        "completed_at": None,
    }


_SELECT_COLS = (
    "id, user_id, workspace_id, platform, native_meeting_id, "
    "capture_bot_id, status, bot_name, intent, store_audio, created_at, completed_at"
)


def _row_to_dict(row) -> dict:
    d = dict(row)
    if d.get("store_audio") is not None:
        d["store_audio"] = bool(d["store_audio"])
    return d


def get_invitation(invitation_id: str) -> Optional[dict]:
    row = _get_conn().execute(
        f"SELECT {_SELECT_COLS} FROM bot_invitations WHERE id = ?",
        (invitation_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def find_by_meeting(platform: str, native_meeting_id: str) -> Optional[dict]:
    """Look up the most recent invitation for a given Meet code."""
    row = _get_conn().execute(
        f"SELECT {_SELECT_COLS} FROM bot_invitations WHERE platform = ? AND native_meeting_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (platform, native_meeting_id),
    ).fetchone()
    return _row_to_dict(row) if row else None


def find_latest_by_native(native_meeting_id: str) -> Optional[dict]:
    """Most recent invitation for a native id across platforms (Task #30 audio gate).

    The audio-chunk write path only knows the meeting id, not the platform, so it
    resolves the per-meeting store-audio decision through this platform-agnostic lookup.
    """
    row = _get_conn().execute(
        f"SELECT {_SELECT_COLS} FROM bot_invitations WHERE native_meeting_id = ? "
        "ORDER BY created_at DESC LIMIT 1",
        (native_meeting_id,),
    ).fetchone()
    return _row_to_dict(row) if row else None


def update_status(
    invitation_id: str,
    status: str,
    *,
    capture_bot_id: Optional[int] = None,
    completed: bool = False,
) -> None:
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    fields: list[str] = ["status = ?"]
    params: list = [status]
    if capture_bot_id is not None:
        fields.append("capture_bot_id = ?")
        params.append(capture_bot_id)
    if completed:
        fields.append("completed_at = ?")
        params.append(_now())
    params.append(invitation_id)
    _get_conn().execute(
        f"UPDATE bot_invitations SET {', '.join(fields)} WHERE id = ?",
        tuple(params),
    )
