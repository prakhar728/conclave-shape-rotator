"""Record-start stash of who is recording an in-person meeting (Task #32).

The in-person live path streams the mic straight to the capture microservice
(untouched — Option B), so the recorder's identity can't ride the WS. The record
flow POSTs it here keyed by the meeting `uid` BEFORE streaming; the
`meeting.completed` webhook pops it and writes `recorder_user_id` onto the
session. That recorder is then passed to VFTE as the `host_user` on identify —
replacing the #2 stopgap where the workspace OWNER stood in as host (so the
per-adder overlay resolves under whoever actually recorded, not the owner).

Mirrors `infra/inperson_agenda` (same key + consume-once lifecycle), kept as a
separate table so #12's agenda stash is untouched.
"""
from __future__ import annotations

from typing import Optional

from storage.sqlite import _get_conn, _now


def set_recorder(uid: str, recorder_user_id: str, *, workspace_id: Optional[str] = None) -> None:
    """Stash (or replace) the recorder for an in-person meeting `uid`.

    Upsert so re-POSTing before Start overwrites. A falsy recorder is a no-op —
    we only want a real user id here (the webhook falls back to the owner if none)."""
    if not recorder_user_id:
        return
    _get_conn().execute(
        "INSERT INTO inperson_recorder (uid, workspace_id, recorder_user_id, created_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET recorder_user_id = excluded.recorder_user_id, "
        "  workspace_id = excluded.workspace_id, created_at = excluded.created_at",
        (uid, workspace_id, recorder_user_id, _now()),
    )


def pop_recorder(uid: str) -> Optional[str]:
    """Return the stashed recorder_user_id for `uid` and delete the row (consume-once).

    Returns None if nothing was stashed (the webhook then falls back to the owner)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT recorder_user_id FROM inperson_recorder WHERE uid = ?", (uid,)
    ).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM inperson_recorder WHERE uid = ?", (uid,))
    return row["recorder_user_id"]
