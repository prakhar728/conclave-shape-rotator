"""Ramp-up trust state — gated→auto graduation by correction rate (#3, #7).

A user starts **gated** (drafts wait for explicit approval). They **graduate to
auto** (drafts auto-approve after a timeout) once they've stopped needing to
correct — measured as the average corrections per meeting over their recent
approved meetings dropping below a threshold. State is DERIVED from the stats, not
stored, so it self-adjusts.
"""
from __future__ import annotations

from storage import sqlite

#: Consider the user's last N approved meetings.
GRADUATION_WINDOW = 3
#: Graduate when avg corrections/meeting over the window is below this.
GRADUATION_THRESHOLD = 2.0


def bump_correction(user_id: str, session_id: str, delta: int = 1) -> None:
    """Record a correction the user made on this draft (called per editor edit)."""
    sqlite.bump_meeting_correction(user_id, session_id, delta)


def finalize(user_id: str, session_id: str) -> None:
    """Mark the meeting approved — it now counts toward the graduation window."""
    sqlite.finalize_meeting_correction(user_id, session_id)


def should_graduate(user_id: str) -> bool:
    counts = sqlite.list_recent_finalized_corrections(user_id, GRADUATION_WINDOW)
    if len(counts) < GRADUATION_WINDOW:
        return False  # not enough history yet
    return (sum(counts) / len(counts)) < GRADUATION_THRESHOLD


def state_for(user_id: str) -> str:
    """'auto' if the user has graduated (low recent correction rate), else 'gated'."""
    return "auto" if should_graduate(user_id) else "gated"
