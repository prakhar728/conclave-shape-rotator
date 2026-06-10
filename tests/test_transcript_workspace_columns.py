"""Tests for the typed workspace columns on `transcript_sessions` (Alembic 0004).

Covers the storage primitives + transcripts.store wrappers added in 1.6.
1.7 will layer `can_see` on top; 1.6 just verifies the columns are writable,
queryable, and constrained.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

import pytest

from infra import identity, workspaces
from storage import sqlite as _sqlite
from storage.sqlite import _get_conn
from transcripts import store as transcripts_store


@pytest.fixture(autouse=True)
def _clean_tables():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")
    reset_workspace_domain_tables()
    yield


def _insert_synthetic_session(session_id: str = "sess-abc") -> None:
    """Bypass the high-level save to control the raw fields directly."""
    _sqlite.save_transcript_session(
        session_id=session_id,
        source="test",
        session_date="2026-06-01",
        raw_diarization=[],
        metadata={"date": "2026-06-01", "source": "test"},
        derived={"summary": "hello"},
    )


def test_new_session_defaults(monkeypatch):
    _insert_synthetic_session()
    row = _sqlite.get_transcript_workspace_fields("sess-abc")
    assert row is not None
    assert row["workspace_id"] is None
    assert row["owner_user_id"] is None
    assert row["visibility"] == "owner-only"


def test_set_workspace_writes_typed_columns():
    user = identity.upsert_user_by_supabase("sb-1", "u@example.com")
    ws = workspaces.create_workspace("Personal", user["id"])
    _insert_synthetic_session()

    transcripts_store.set_workspace(
        "sess-abc",
        workspace_id=ws["id"],
        owner_user_id=user["id"],
        visibility="shared",
    )

    row = _sqlite.get_transcript_workspace_fields("sess-abc")
    assert row == {
        "workspace_id": ws["id"],
        "owner_user_id": user["id"],
        "visibility": "shared",
        # Retention columns ride along additively (Alembic 0012) — unset here.
        "retention_override": None,
        "raw_transcript_deleted_at": None,
    }


def test_set_workspace_preserves_visibility_when_omitted():
    user = identity.upsert_user_by_supabase("sb-2", "u2@example.com")
    ws = workspaces.create_workspace("WS2", user["id"])
    _insert_synthetic_session()

    # Bind workspace without touching visibility — stays at the default.
    transcripts_store.set_workspace("sess-abc", ws["id"], user["id"])
    row = _sqlite.get_transcript_workspace_fields("sess-abc")
    assert row["visibility"] == "owner-only"


def test_visibility_check_constraint_rejects_unknown_value():
    _insert_synthetic_session()
    with pytest.raises(sqlite3.IntegrityError):
        _get_conn().execute(
            "UPDATE transcript_sessions SET visibility = 'bogus' WHERE session_id = ?",
            ("sess-abc",),
        )


def test_list_workspace_sessions_filters_by_workspace():
    a = identity.upsert_user_by_supabase("sb-a", "a@example.com")
    b = identity.upsert_user_by_supabase("sb-b", "b@example.com")
    ws_a = workspaces.create_workspace("A", a["id"])
    ws_b = workspaces.create_workspace("B", b["id"])

    _insert_synthetic_session("s-a1")
    _insert_synthetic_session("s-a2")
    _insert_synthetic_session("s-b1")
    _insert_synthetic_session("s-orphan")  # no workspace

    transcripts_store.set_workspace("s-a1", ws_a["id"], a["id"])
    transcripts_store.set_workspace("s-a2", ws_a["id"], a["id"])
    transcripts_store.set_workspace("s-b1", ws_b["id"], b["id"])

    a_sessions = {s.session_id for s in transcripts_store.list_workspace_sessions(ws_a["id"])}
    b_sessions = {s.session_id for s in transcripts_store.list_workspace_sessions(ws_b["id"])}
    assert a_sessions == {"s-a1", "s-a2"}
    assert b_sessions == {"s-b1"}


def test_meetings_endpoint_now_returns_workspace_sessions(monkeypatch):
    """End-to-end via TestClient — proves the API contract from 1.5 now lights up."""
    from fastapi.testclient import TestClient

    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "send_otp", lambda email: None)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")

    from main import app
    client = TestClient(app)
    r = client.post("/auth/v1/verify-otp", json={"email": "alice@example.com", "token": "000000"})
    assert r.status_code == 200
    body = r.json()
    user_id = body["user"]["id"]
    ws_id = body["workspace"]["id"]

    _insert_synthetic_session("alice-sess-1")
    transcripts_store.set_workspace("alice-sess-1", ws_id, user_id)

    r2 = client.get(f"/api/workspaces/{ws_id}/meetings")
    assert r2.status_code == 200
    meetings = r2.json()["meetings"]
    assert len(meetings) == 1
    assert meetings[0]["session_id"] == "alice-sess-1"
    assert meetings[0]["summary"] == "hello"
