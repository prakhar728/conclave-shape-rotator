"""CRUD over `calendar_auto_record` (Alembic 0011).

Per-event opt-in for the auto-dispatch poller: a row with enabled=1 means
"send the Conclave bot to this Google Meet when it's about to start". The
poller (infra/scheduler.py) reads enabled rows; the toggle endpoint
(api/calendar_routes.py) writes them.
"""
from __future__ import annotations

from typing import Optional

from storage.sqlite import _get_conn, _now


def set_auto_record(
    *,
    user_id: str,
    google_event_id: str,
    workspace_id: str,
    meet_code: Optional[str],
    enabled: bool,
) -> None:
    """Upsert the opt-in row for (user, event)."""
    now = _now()
    conn = _get_conn()
    existing = conn.execute(
        "SELECT 1 FROM calendar_auto_record WHERE user_id = ? AND google_event_id = ?",
        (user_id, google_event_id),
    ).fetchone()
    if existing is None:
        conn.execute(
            "INSERT INTO calendar_auto_record "
            "(user_id, google_event_id, workspace_id, meet_code, enabled, "
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, google_event_id, workspace_id, meet_code,
             1 if enabled else 0, now, now),
        )
    else:
        conn.execute(
            "UPDATE calendar_auto_record SET workspace_id = ?, meet_code = ?, "
            "enabled = ?, updated_at = ? WHERE user_id = ? AND google_event_id = ?",
            (workspace_id, meet_code, 1 if enabled else 0, now,
             user_id, google_event_id),
        )


def enabled_event_ids(user_id: str) -> set[str]:
    """Google event ids the user has opted into auto-recording."""
    rows = _get_conn().execute(
        "SELECT google_event_id FROM calendar_auto_record "
        "WHERE user_id = ? AND enabled = 1",
        (user_id,),
    ).fetchall()
    return {r["google_event_id"] for r in rows}


def find_by_meet_code(meet_code: str) -> Optional[dict]:
    """Most recent opt-in row carrying this Meet code, regardless of enabled
    state. The webhook uses it to recover the Google event id behind a
    recorded meeting."""
    row = _get_conn().execute(
        "SELECT user_id, google_event_id, workspace_id, meet_code, enabled "
        "FROM calendar_auto_record WHERE meet_code = ? "
        "ORDER BY updated_at DESC LIMIT 1",
        (meet_code,),
    ).fetchone()
    return dict(row) if row else None


def list_enabled_for_user(user_id: str) -> list[dict]:
    """Full enabled rows for one user (poller uses workspace_id + meet_code)."""
    rows = _get_conn().execute(
        "SELECT user_id, google_event_id, workspace_id, meet_code, enabled "
        "FROM calendar_auto_record WHERE user_id = ? AND enabled = 1",
        (user_id,),
    ).fetchall()
    return [dict(r) for r in rows]
