"""HTTP tests for /api/magic-links/* + the verify-otp auto-grant (2.11)."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra import identity, magic_links, workspaces
from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM magic_links")
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


def test_lookup_unknown_token_404(client: TestClient):
    r = client.get("/api/magic-links/no-such-token")
    assert r.status_code == 404


def test_lookup_valid_token_public(client: TestClient):
    token = magic_links.issue(
        user_email="bob@example.com", meeting_session_id="sess-abc"
    )
    r = client.get(f"/api/magic-links/{token}")
    assert r.status_code == 200
    body = r.json()
    assert body["meeting_session_id"] == "sess-abc"
    assert body["user_email"] == "bob@example.com"
    assert body["consumed_at"] is None


def test_consume_marks_consumed(client: TestClient):
    token = magic_links.issue(
        user_email="bob@example.com", meeting_session_id="sess-abc"
    )
    r = client.post(f"/api/magic-links/{token}/consume")
    assert r.status_code == 200
    assert r.json()["consumed_at"] is not None


# --- 2.11 auto-grant on first signup --------------------------------------


def test_verify_otp_backfills_user_id_on_existing_shares(client: TestClient):
    # Owner shares a meeting with bob's email BEFORE bob has signed up.
    owner = identity.upsert_user_by_supabase("sb-owner", "owner@example.com")
    workspaces.add_meeting_share("sess-1", "bob@example.com", owner["id"])

    # Bob never logged in before — user_id on the share should be NULL.
    row = _get_conn().execute(
        "SELECT user_id FROM meeting_shares WHERE user_email = ?",
        ("bob@example.com",),
    ).fetchone()
    assert row["user_id"] is None

    # Bob signs in for the first time.
    r = client.post(
        "/auth/v1/verify-otp", json={"email": "bob@example.com", "token": "000000"}
    )
    assert r.status_code == 200
    bob_id = r.json()["user"]["id"]

    # The share row now points at bob.
    row = _get_conn().execute(
        "SELECT user_id FROM meeting_shares WHERE user_email = ?",
        ("bob@example.com",),
    ).fetchone()
    assert row["user_id"] == bob_id


def test_verify_otp_doesnt_clobber_user_id_when_already_set(client: TestClient):
    # Match the test client's verify_otp stub format (sb-<email>) so
    # the second OTP call hits the existing user row instead of trying
    # to create a duplicate.
    bob = identity.upsert_user_by_supabase("sb-bob@example.com", "bob@example.com")
    owner = identity.upsert_user_by_supabase("sb-owner", "owner@example.com")
    _get_conn().execute(
        "INSERT INTO meeting_shares (session_id, user_email, granted_by, granted_at, user_id) "
        "VALUES ('sess-x', 'bob@example.com', ?, '2026-06-01T00:00:00Z', ?)",
        (owner["id"], bob["id"]),
    )
    client.post(
        "/auth/v1/verify-otp", json={"email": "bob@example.com", "token": "000000"}
    )
    row = _get_conn().execute(
        "SELECT user_id FROM meeting_shares WHERE session_id = ?",
        ("sess-x",),
    ).fetchone()
    # Still the original (bob); the backfill query is WHERE user_id IS NULL.
    assert row["user_id"] == bob["id"]
