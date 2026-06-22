"""Part 1 increment 9b/9c — auto-approval timeout sweep.

Auto-graduated users' draft transcripts auto-approve after their timeout window;
gated users' drafts never auto-approve (they wait for explicit approval).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

import api.transcripts_routes as routes
from transcripts import trust

_OLD = "2020-01-01T00:00:00Z"
_NOW = datetime.now(timezone.utc).isoformat() + "Z"


@pytest.fixture
def captured(monkeypatch):
    approved = []
    monkeypatch.setattr(routes, "approve_and_build", lambda sid: approved.append(sid))
    monkeypatch.setattr(routes, "_ws_row", lambda sid: {"owner_user_id": "owner"})
    return approved


def test_sweep_auto_approves_old_auto_draft(captured, monkeypatch):
    monkeypatch.setattr(routes.store, "list_draft_v2_sessions",
                        lambda: [{"session_id": "old", "created_at": _OLD},
                                 {"session_id": "fresh", "created_at": _NOW}])
    monkeypatch.setattr(trust, "state_for", lambda uid: "auto")
    out = routes.run_timeout_sweep()
    assert out == ["old"]  # old past timeout; fresh not yet
    assert captured == ["old"]


def test_sweep_skips_gated(captured, monkeypatch):
    monkeypatch.setattr(routes.store, "list_draft_v2_sessions",
                        lambda: [{"session_id": "old", "created_at": _OLD}])
    monkeypatch.setattr(trust, "state_for", lambda uid: "gated")
    assert routes.run_timeout_sweep() == []  # gated never auto-approved
    assert captured == []


def test_sweep_skips_unowned(captured, monkeypatch):
    monkeypatch.setattr(routes.store, "list_draft_v2_sessions",
                        lambda: [{"session_id": "old", "created_at": _OLD}])
    monkeypatch.setattr(routes, "_ws_row", lambda sid: None)  # legacy / no owner
    monkeypatch.setattr(trust, "state_for", lambda uid: "auto")
    assert routes.run_timeout_sweep() == []
