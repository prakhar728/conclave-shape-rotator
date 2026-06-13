"""Link recorded meetings back to the calendar event they came from.

`meeting_calendar_links` (Alembic 0011) stores, per Meet code, the event's
title / organizer / attendees / scheduled time, so a transcript carries its
calendar context. The Recato meeting.completed webhook calls
`link_completed_meeting` after binding the session to a workspace.

We can only resolve the calendar event for meetings we know the Google event
id of — i.e. ones that went through auto-record (calendar_auto_record holds
the event id ↔ meet code mapping). Manually-invited meetings with no such
row simply don't get linked (returns None), which is fine: linking is
best-effort enrichment, never load-bearing.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from storage.sqlite import _get_conn, _now

logger = logging.getLogger(__name__)


def save_link(*, meet_code: str, session_id: Optional[str], event: dict) -> None:
    """Upsert the calendar link for a meeting (keyed by Meet code)."""
    attendees = json.dumps(event.get("attendees") or [])
    now = _now()
    conn = _get_conn()
    exists = conn.execute(
        "SELECT 1 FROM meeting_calendar_links WHERE meet_code = ?", (meet_code,)
    ).fetchone()
    if exists is None:
        conn.execute(
            "INSERT INTO meeting_calendar_links "
            "(meet_code, session_id, google_event_id, title, organizer_email, "
            " attendees_json, start_at, end_at, linked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (meet_code, session_id, event.get("id"), event.get("title"),
             event.get("organizer"), attendees, event.get("start"),
             event.get("end"), now),
        )
    else:
        conn.execute(
            "UPDATE meeting_calendar_links SET session_id = ?, google_event_id = ?, "
            "title = ?, organizer_email = ?, attendees_json = ?, start_at = ?, "
            "end_at = ?, linked_at = ? WHERE meet_code = ?",
            (session_id, event.get("id"), event.get("title"), event.get("organizer"),
             attendees, event.get("start"), event.get("end"), now, meet_code),
        )


def get_link(meet_code: str) -> Optional[dict]:
    row = _get_conn().execute(
        "SELECT meet_code, session_id, google_event_id, title, organizer_email, "
        "attendees_json, start_at, end_at, linked_at "
        "FROM meeting_calendar_links WHERE meet_code = ?",
        (meet_code,),
    ).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["attendees"] = json.loads(d.pop("attendees_json") or "[]")
    return d


def link_completed_meeting(
    *,
    meet_code: str,
    session_id: Optional[str],
    inviter_user_id: Optional[str],
) -> Optional[dict]:
    """Best-effort: resolve the calendar event behind a recorded meeting,
    persist the link, and auto-share the transcript with the event's
    attendees. Returns the stored link, or None if no event could be
    resolved (and never raises — callers treat it as optional enrichment)."""
    from infra import calendar_auto_record as car
    from infra import google_calendar as gc
    from infra import workspaces

    ar_row = car.find_by_meet_code(meet_code)
    if ar_row is None:
        return None  # not an auto-recorded meeting; nothing to link

    # Prefer the inviter's connection to read the event; fall back to the
    # opt-in owner (they're usually the same user).
    candidates = [uid for uid in (inviter_user_id, ar_row["user_id"]) if uid]
    event = None
    for uid in candidates:
        if not gc.is_connected(uid):
            continue
        try:
            event = gc.get_event(uid, ar_row["google_event_id"])
            granter = uid
            break
        except (gc.GoogleOAuthError, gc.GoogleCalendarError) as e:
            logger.warning("link: get_event failed for %s/%s: %s", uid, meet_code, e)
    if event is None:
        return None

    save_link(meet_code=meet_code, session_id=session_id, event=event)

    # Calendar agenda/description → per-meeting enrichment intent. Only fill when
    # no manual intent is already set (a manual /invite-bot "focus" wins).
    # Best-effort — never abort linking over it.
    desc = (event.get("description") or "").strip()
    if session_id and desc:
        try:
            from transcripts import store as _store
            sess = _store.load_session(session_id)
            if sess is not None and not (sess.metadata.raw_intent or "").strip():
                sess.metadata.raw_intent = desc
                _store.set_metadata(session_id, sess.metadata)
        except Exception:  # noqa: BLE001 — intent is optional grounding
            logger.exception("link: failed to set raw_intent for %s", session_id)

    # Auto-share the recorded meeting with each attendee (keyed by Meet code,
    # matching the manual /invite-bot share convention). Idempotent on the
    # store side.
    for email in event.get("attendees") or []:
        try:
            workspaces.add_meeting_share(meet_code, email, granter)
        except Exception:  # noqa: BLE001 — one bad email shouldn't abort linking
            logger.exception("link: failed to share %s with %s", meet_code, email)

    return get_link(meet_code)
