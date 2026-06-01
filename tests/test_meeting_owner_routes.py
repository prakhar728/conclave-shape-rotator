"""Tests for visibility toggle + shares list/add on /api/meetings/* (Phase 2.12, 2.13)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra import bot_invitations, identity, workspaces
from storage import sqlite as _sqlite
from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")
    _get_conn().execute("DELETE FROM bot_invitations")
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def client(monkeypatch) -> TestClient:
    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "send_otp", lambda email: None)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    from main import app
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200
    return r.json()


def _seed_completed_meeting(*, owner_email: str, session_id: str = "sess-x") -> dict:
    """Simulate a post-webhook completed meeting belonging to `owner_email`."""
    owner = identity.upsert_user_by_supabase(f"sb-{owner_email}", owner_email)
    ws = workspaces.create_workspace("Personal", owner["id"])
    _sqlite.save_transcript_session(
        session_id=session_id,
        source="recato",
        session_date="2026-06-01",
        raw_diarization=[],
        metadata={"date": "2026-06-01", "source": "recato"},
        derived={"summary": "demo"},
    )
    _sqlite.set_transcript_workspace(
        session_id=session_id,
        workspace_id=ws["id"],
        owner_user_id=owner["id"],
        visibility="owner-only",
    )
    return {"owner": owner, "workspace": ws, "session_id": session_id}


def test_visibility_toggle_round_trip(client: TestClient):
    seed = _seed_completed_meeting(owner_email="owner@example.com")
    _login(client, "owner@example.com")

    r = client.post(
        f"/api/meetings/{seed['session_id']}/visibility",
        json={"visibility": "shared"},
    )
    assert r.status_code == 200
    fields = _sqlite.get_transcript_workspace_fields(seed["session_id"])
    assert fields["visibility"] == "shared"

    r2 = client.post(
        f"/api/meetings/{seed['session_id']}/visibility",
        json={"visibility": "owner-only"},
    )
    assert r2.status_code == 200
    assert _sqlite.get_transcript_workspace_fields(seed["session_id"])["visibility"] == "owner-only"


def test_visibility_rejects_unallowed_values(client: TestClient):
    seed = _seed_completed_meeting(owner_email="z@example.com")
    _login(client, "z@example.com")
    for bad in ("workspace", "public-link", "wrong"):
        r = client.post(
            f"/api/meetings/{seed['session_id']}/visibility",
            json={"visibility": bad},
        )
        assert r.status_code == 422


def test_visibility_only_owner_can(client: TestClient):
    seed = _seed_completed_meeting(owner_email="own@example.com")
    _login(client, "stranger@example.com")
    r = client.post(
        f"/api/meetings/{seed['session_id']}/visibility",
        json={"visibility": "shared"},
    )
    assert r.status_code == 404


def test_list_shares_owner_only(client: TestClient):
    seed = _seed_completed_meeting(owner_email="ls@example.com")
    workspaces.add_meeting_share(seed["session_id"], "guest@example.com", seed["owner"]["id"])
    _login(client, "ls@example.com")
    r = client.get(f"/api/meetings/{seed['session_id']}/shares")
    assert r.status_code == 200
    assert [s["email"] for s in r.json()["shares"]] == ["guest@example.com"]


def test_list_shares_non_owner_404(client: TestClient):
    seed = _seed_completed_meeting(owner_email="lsno@example.com")
    _login(client, "outsider@example.com")
    r = client.get(f"/api/meetings/{seed['session_id']}/shares")
    assert r.status_code == 404


def test_add_share_via_transcript_owner_path(client: TestClient):
    """Phase 2.13 supports post-completion adds (no bot_invitation needed)."""
    seed = _seed_completed_meeting(owner_email="post@example.com")
    _login(client, "post@example.com")
    r = client.post(
        f"/api/meetings/{seed['session_id']}/shares",
        json={"email": "late@example.com"},
    )
    assert r.status_code == 201
    from infra.workspaces import has_meeting_share
    assert has_meeting_share(seed["session_id"], "late@example.com")


def test_add_share_via_pre_completion_invitation_path(client: TestClient):
    """Owner can pre-seed shares before the webhook fires (via bot_invitation)."""
    me = _login(client, "pre@example.com")
    bot_invitations.create_invitation(
        user_id=me["user"]["id"],
        workspace_id=me["workspace"]["id"],
        platform="google_meet",
        native_meeting_id="abc-defg-hij",
        status="joining",
    )
    r = client.post(
        "/api/meetings/abc-defg-hij/shares",
        json={"email": "future@example.com"},
    )
    assert r.status_code == 201
