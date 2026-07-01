"""CRUD over the `inperson_agenda` stash (Alembic 0023) — Task #12.

The in-person record modal POSTs the agenda the user typed, keyed by the meeting
`uid`, BEFORE the meeting streams (capture is untouched, so the agenda can't ride
the WS). The `meeting.completed` webhook later reads it back by `uid`
(== `native_meeting_id`) and applies it as `session.metadata.raw_intent` before
enrichment runs — giving in-person summaries the same agenda grounding online +
upload meetings get (the `raw_intent → compile_intent → <meeting_intent>` chain).

`pop_agenda` reads-and-deletes so a consumed agenda can't linger or be re-applied
on a duplicate finalize. Writes upsert so editing the agenda before Start wins.
"""
from __future__ import annotations

from typing import Optional

from storage.sqlite import _get_conn, _now


def set_agenda(uid: str, agenda: str, *, workspace_id: Optional[str] = None) -> None:
    """Stash (or replace) the agenda for an in-person meeting `uid`.

    Upsert so re-POSTing before Start (e.g. the user edits the field) overwrites.
    Empty/whitespace agendas are not stored — they'd add no grounding and would
    only mask a later real value."""
    if not agenda or not agenda.strip():
        return
    _get_conn().execute(
        "INSERT INTO inperson_agenda (uid, workspace_id, agenda, created_at) "
        "VALUES (?, ?, ?, ?) "
        "ON CONFLICT(uid) DO UPDATE SET agenda = excluded.agenda, "
        "  workspace_id = excluded.workspace_id, created_at = excluded.created_at",
        (uid, workspace_id, agenda.strip(), _now()),
    )


def pop_agenda(uid: str) -> Optional[str]:
    """Return the stashed agenda for `uid` and delete the row (consume-once).

    Returns None if nothing was stashed. Deleting on read keeps the stash from
    growing unbounded and prevents a re-apply if the webhook fires twice."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT agenda FROM inperson_agenda WHERE uid = ?", (uid,)
    ).fetchone()
    if row is None:
        return None
    conn.execute("DELETE FROM inperson_agenda WHERE uid = ?", (uid,))
    return row["agenda"]
