"""Round-trip CRUD tests for infra/identity.py + infra/workspaces.py.

Lightweight smoke — confirms Alembic 0002 schema is reachable from the test
DB and the helper modules behave as expected. Phase 1.5 routes layer on top.
"""
from __future__ import annotations

import pytest

from infra import identity, workspaces


@pytest.fixture(autouse=True)
def _clean_tables():
    """Wipe the workspace-domain tables before each test for isolation."""
    from tests.conftest import reset_workspace_domain_tables
    reset_workspace_domain_tables()
    yield


def test_upsert_user_creates_then_returns_existing():
    u1 = identity.upsert_user_by_supabase("sb-1", "a@x.test", "Alice")
    assert u1["id"].startswith("usr_")
    assert u1["email"] == "a@x.test"
    assert u1["display_name"] == "Alice"

    # Same supabase_id → same row.
    u2 = identity.upsert_user_by_supabase("sb-1", "a@x.test", "Alice")
    assert u2["id"] == u1["id"]


def test_upsert_user_updates_drifted_fields():
    u1 = identity.upsert_user_by_supabase("sb-2", "old@x.test", "Old")
    u2 = identity.upsert_user_by_supabase("sb-2", "new@x.test", "New")
    assert u2["id"] == u1["id"]
    assert u2["email"] == "new@x.test"
    assert u2["display_name"] == "New"
    assert u2["updated_at"] >= u1["updated_at"]


def test_lookup_by_email_and_supabase():
    u = identity.upsert_user_by_supabase("sb-3", "c@x.test", "Carol")
    assert identity.get_user(u["id"])["id"] == u["id"]
    assert identity.get_user_by_email("c@x.test")["id"] == u["id"]
    assert identity.get_user_by_supabase("sb-3")["id"] == u["id"]
    assert identity.get_user_by_email("nope@x.test") is None


def test_workspace_create_and_owner_membership():
    user = identity.upsert_user_by_supabase("sb-w1", "w@x.test", "W")
    ws = workspaces.create_workspace("Personal", user["id"])
    assert ws["id"].startswith("ws_")
    assert ws["name"] == "Personal"
    assert ws["created_by"] == user["id"]

    assert workspaces.is_member(ws["id"], user["id"]) is True
    assert workspaces.get_member_role(ws["id"], user["id"]) == "owner"


def test_ensure_personal_workspace_is_idempotent():
    user = identity.upsert_user_by_supabase("sb-w2", "w2@x.test", "W2")
    ws1 = workspaces.ensure_personal_workspace(user["id"])
    ws2 = workspaces.ensure_personal_workspace(user["id"])
    assert ws1["id"] == ws2["id"]
    assert workspaces.list_user_workspaces(user["id"]) == [
        {**ws1, "role": "owner"},
    ] or len(workspaces.list_user_workspaces(user["id"])) == 1


def test_non_member_lookup():
    a = identity.upsert_user_by_supabase("sb-a", "a@x.test", "A")
    b = identity.upsert_user_by_supabase("sb-b", "b@x.test", "B")
    ws = workspaces.create_workspace("A's WS", a["id"])
    assert workspaces.is_member(ws["id"], b["id"]) is False
    assert workspaces.get_member_role(ws["id"], b["id"]) is None


def test_meeting_share_idempotent():
    a = identity.upsert_user_by_supabase("sb-share", "owner@x.test", "Owner")
    workspaces.add_meeting_share("sess-123", "guest@x.test", a["id"])
    workspaces.add_meeting_share("sess-123", "guest@x.test", a["id"])
    shares = workspaces.list_meeting_shares("sess-123")
    assert len(shares) == 1
    assert shares[0]["user_email"] == "guest@x.test"
    assert workspaces.has_meeting_share("sess-123", "guest@x.test") is True
    assert workspaces.has_meeting_share("sess-123", "missing@x.test") is False


def test_role_check_constraint_rejects_unknown_role():
    """DDL CHECK constraint should reject roles outside the allowed set."""
    import sqlite3

    from storage.sqlite import _get_conn, _now

    user = identity.upsert_user_by_supabase("sb-role", "r@x.test", "R")
    ws = workspaces.create_workspace("WS", user["id"])
    # Direct insert bypassing the helper to trigger the CHECK.
    with pytest.raises(sqlite3.IntegrityError):
        _get_conn().execute(
            "INSERT INTO workspace_members (workspace_id, user_id, role, added_at) "
            "VALUES (?, ?, 'admin', ?)",
            (ws["id"], user["id"], _now()),
        )
