"""Auto-dispatch: send the Conclave bot to soon-starting calendar meetings.

The scheduler (infra/scheduler.py) calls `dispatch_due_meetings()` on a
fixed cadence. For each Google-connected user we list events starting within
a small look-ahead window, keep those the user opted into auto-recording
(calendar_auto_record) that carry a Meet link, dedup against existing
bot_invitations, and launch via the same Recato path the manual
/invite-bot endpoint uses.

Kept separate from the asyncio loop so the core decision logic is unit
testable without spinning up an event loop or real timers.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from connectors.recato.launch import (
    DEFAULT_BOT_NAME,
    RecatoLaunchError,
    launch_bot,
)
from infra import bot_invitations
from infra import calendar_auto_record as car
from infra import google_calendar as gc
from infra import identity

logger = logging.getLogger(__name__)

# How far ahead to look for meetings about to start.
LOOKAHEAD_MIN = 5
# A completed invitation younger than this blocks re-dispatch (so a recurring
# event sharing one Meet code isn't re-recorded for the same occurrence);
# older completions don't block (tomorrow's occurrence still records).
RECENT_COMPLETION_H = 2


def _parse_storage_ts(ts: Optional[str]) -> Optional[datetime]:
    """Parse a storage `_now()` timestamp ('...isoformat()+Z', naive UTC)."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.rstrip("Z"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def _already_handled(meet_code: str, now: datetime) -> bool:
    """True if an existing invitation means we should NOT dispatch again."""
    inv = bot_invitations.find_by_meeting("google_meet", meet_code)
    if inv is None:
        return False
    if inv["status"] in ("requested", "joining", "active"):
        return True  # in-flight
    if inv["status"] == "completed":
        done = _parse_storage_ts(inv.get("completed_at"))
        if done is not None and (now - done) < timedelta(hours=RECENT_COMPLETION_H):
            return True  # just recorded this occurrence
    # 'failed' or an old completion → allow a fresh attempt.
    return False


def due_meetings_for_user(user_id: str, *, now: datetime, lookahead_min: int = LOOKAHEAD_MIN) -> list[dict]:
    """Meetings to dispatch the bot to, starting within the look-ahead window
    and carrying a Meet link. Returns dicts: {event_id, meet_code,
    workspace_id, title}.

    Two ways an event qualifies:
      1. Per-event opt-in (`calendar_auto_record` enabled=1) — its own workspace.
      2. Account-wide "record all my meetings" (user setting) — covers every
         Meet the user hasn't explicitly opted out of, into the chosen workspace.
    A per-event opt-in/opt-out always beats the account-wide default.
    """
    enabled_rows = car.list_enabled_for_user(user_id)
    ws_by_event = {r["google_event_id"]: r["workspace_id"] for r in enabled_rows}
    enabled_ids = set(ws_by_event)

    all_ws = identity.get_auto_record_all_workspace(user_id)
    opted_out = car.disabled_event_ids(user_id) if all_ws else set()

    if not enabled_ids and not all_ws:
        return []

    events = gc.list_events(
        user_id,
        time_min=now.isoformat(),
        time_max=(now + timedelta(minutes=lookahead_min)).isoformat(),
    )
    due = []
    for ev in events:
        if not ev["meet_code"]:
            continue
        if ev["id"] in enabled_ids:
            workspace_id = ws_by_event[ev["id"]]      # explicit opt-in wins
        elif all_ws and ev["id"] not in opted_out:
            workspace_id = all_ws                      # account-wide record-all
        else:
            continue
        due.append({
            "event_id": ev["id"],
            "meet_code": ev["meet_code"],
            "workspace_id": workspace_id,
            "title": ev["title"],
        })
    return due


def dispatch_for_user(user_id: str, *, now: datetime, lookahead_min: int = LOOKAHEAD_MIN) -> list[str]:
    """Dispatch the bot to this user's due meetings. Returns the meet codes
    actually launched (deduped). Best-effort: a single failed launch is
    logged and skipped, not fatal to the rest."""
    webhook_url = os.environ.get("RECATO_MEETING_COMPLETED_URL")
    launched: list[str] = []
    for item in due_meetings_for_user(user_id, now=now, lookahead_min=lookahead_min):
        meet_code = item["meet_code"]
        if _already_handled(meet_code, now):
            continue
        inv = bot_invitations.create_invitation(
            user_id=user_id,
            workspace_id=item["workspace_id"],
            platform="google_meet",
            native_meeting_id=meet_code,
            bot_name=DEFAULT_BOT_NAME,
            status="requested",
        )
        try:
            resp = launch_bot(
                platform="google_meet",
                native_meeting_id=meet_code,
                bot_name=DEFAULT_BOT_NAME,
                webhook_url=webhook_url,
            )
        except RecatoLaunchError as e:
            logger.warning("auto-dispatch: launch failed for %s: %s", meet_code, e)
            bot_invitations.update_status(inv["id"], "failed", completed=True)
            continue
        recato_bot_id = resp.get("id") if isinstance(resp, dict) and isinstance(resp.get("id"), int) else None
        bot_invitations.update_status(inv["id"], "joining", recato_bot_id=recato_bot_id)
        logger.info("auto-dispatch: launched bot for %s (event %s)", meet_code, item["event_id"])
        launched.append(meet_code)
    return launched


def dispatch_due_meetings(*, now: Optional[datetime] = None, lookahead_min: int = LOOKAHEAD_MIN) -> int:
    """One poll tick across all connected users. Returns count launched."""
    now = now or datetime.now(timezone.utc)
    total = 0
    for user_id in gc.list_connected_user_ids():
        try:
            total += len(dispatch_for_user(user_id, now=now, lookahead_min=lookahead_min))
        except (gc.GoogleOAuthError, gc.GoogleCalendarError) as e:
            # One user's expired/revoked token shouldn't stall everyone else.
            logger.warning("auto-dispatch: skipping user %s: %s", user_id, e)
    return total
