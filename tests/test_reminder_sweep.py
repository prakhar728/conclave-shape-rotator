"""Part 1 increment 9d — post-meeting review reminder (BOTH user types, once).

Fires for any owned draft whose meeting ended ~CONCLAVE_REFINE_REMINDER_HOURS ago,
regardless of trust state, and exactly once (reminded_at gates it).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import api.transcripts_routes as routes
from transcripts import candidate, store
from transcripts.models import RawSegment, Session, SessionMetadata

_OLD = "2020-01-01T00:00:00Z"
_NOW = datetime.now(timezone.utc).isoformat() + "Z"


@pytest.fixture
def sent(monkeypatch):
    s = []
    monkeypatch.setattr(routes, "_send_review_reminder", lambda sid, owner: s.append(sid))
    monkeypatch.setattr(routes, "_ws_row", lambda sid: {"owner_user_id": "owner"})
    monkeypatch.setattr(routes.store, "mark_v2_reminded", lambda sid: None)
    return s


def test_reminder_fires_for_old_draft(sent, monkeypatch):
    monkeypatch.setattr(routes.store, "list_unreminded_draft_v2",
                        lambda: [{"session_id": "old", "created_at": _OLD},
                                 {"session_id": "fresh", "created_at": _NOW}])
    assert routes.run_reminder_sweep() == ["old"]
    assert sent == ["old"]  # fresh is too soon


def test_reminder_skips_unowned(sent, monkeypatch):
    monkeypatch.setattr(routes.store, "list_unreminded_draft_v2",
                        lambda: [{"session_id": "old", "created_at": _OLD}])
    monkeypatch.setattr(routes, "_ws_row", lambda sid: None)
    assert routes.run_reminder_sweep() == []


def test_reminder_fires_once_real(monkeypatch):
    # real DB: reminded_at gates the second sweep. Negative window → fresh draft eligible.
    monkeypatch.setenv("CONCLAVE_REFINE_REMINDER_HOURS", "-1")
    monkeypatch.setattr(routes, "_send_review_reminder", lambda sid, owner: None)
    monkeypatch.setattr(routes, "_ws_row", lambda sid: {"owner_user_id": "owner"})
    monkeypatch.setattr(candidate, "detect", lambda t, u: (t.split(), []))
    store.save_session(Session(
        session_id="rem1",
        raw_diarization=[RawSegment(speaker="s", text="hi")],
        metadata=SessionMetadata(date="2026-06-22", source="t"),
    ))
    store.create_v2_draft("rem1")
    assert "rem1" in routes.run_reminder_sweep()
    assert "rem1" not in routes.run_reminder_sweep()  # reminded exactly once
