"""Tests for /auth/v1/exchange-token (OAuth + magic-link path).

Supabase JWKS validation is monkeypatched — we return a synthetic decoded
payload instead of doing real ES256 verification. The actual JWKS path is
exercised by the existing infra/supabase_auth.py code.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra import workspaces
from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def client(monkeypatch) -> TestClient:
    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    from main import app
    return TestClient(app)


def _stub_validate(monkeypatch, *, email: str, sub: str = "sb-123"):
    """Make _supabase_validate return a synthetic payload."""
    import auth.routes as ar
    monkeypatch.setattr(
        ar, "_supabase_validate", lambda tok: {"sub": sub, "email": email}
    )


def test_unconfigured_supabase_returns_503(client: TestClient, monkeypatch):
    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: False)
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: False)
    r = client.post("/auth/v1/exchange-token", json={"access_token": "x"})
    assert r.status_code == 503


def test_invalid_jwt_returns_401(client: TestClient, monkeypatch):
    import auth.routes as ar

    def _raise(tok):
        raise ValueError("bad sig")

    monkeypatch.setattr(ar, "_supabase_validate", _raise)
    r = client.post("/auth/v1/exchange-token", json={"access_token": "garbage"})
    assert r.status_code == 401


def test_missing_email_claim_returns_401(client: TestClient, monkeypatch):
    import auth.routes as ar
    monkeypatch.setattr(
        ar, "_supabase_validate", lambda tok: {"sub": "sb-1"}  # no email
    )
    r = client.post("/auth/v1/exchange-token", json={"access_token": "x"})
    assert r.status_code == 401
    assert "email" in r.json()["detail"].lower()


def _invite_email_to_new_ws(email: str, *, name: str = "demo-ws", role: str = "owner") -> dict:
    """Seed a workspace + pending invite for `email` (mirrors the boot seeder)."""
    from infra import identity
    admin = identity.upsert_user_by_supabase("sb-seed-admin", "admin@example.com")
    ws = workspaces.create_workspace(name, admin["id"])
    workspaces.create_invite(ws["id"], email, role=role, invited_by=admin["id"])
    return ws


def test_invited_email_connects_and_lands_in_workspace(client: TestClient, monkeypatch):
    # Task #9 link-only: a pre-issued invite → accept-on-connect → lands in that ws.
    ws = _invite_email_to_new_ws("prakhar@example.com")
    _stub_validate(monkeypatch, email="prakhar@example.com", sub="sb-oauth-1")
    r = client.post("/auth/v1/exchange-token", json={"access_token": "ok"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "prakhar@example.com"
    assert body["workspace"]["id"] == ws["id"]
    assert body["workspace"]["name"] == "demo-ws"
    from auth.session import COOKIE_NAME
    assert COOKIE_NAME in client.cookies
    me = client.get("/auth/v1/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "prakhar@example.com"


def test_uninvited_user_gets_personal_workspace(client: TestClient, monkeypatch):
    # #25: no more link-only 403 — every authenticated user auto-gets a solo `Personal` workspace.
    _stub_validate(monkeypatch, email="stranger@example.com", sub="sb-stranger")
    r = client.post("/auth/v1/exchange-token", json={"access_token": "ok"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["workspace"]["name"] == "Personal"
    assert body["user"]["email"] == "stranger@example.com"
    # web fix: the session token is returned in the body (Vercel rewrites eat the cookie)
    assert body.get("session_token")


def test_oauth_is_idempotent_on_same_user(client: TestClient, monkeypatch):
    _invite_email_to_new_ws("dup@example.com")
    _stub_validate(monkeypatch, email="dup@example.com", sub="sb-same")
    r1 = client.post("/auth/v1/exchange-token", json={"access_token": "a"})
    r2 = client.post("/auth/v1/exchange-token", json={"access_token": "b"})
    assert r1.status_code == 200 and r2.status_code == 200
    assert r1.json()["user"]["id"] == r2.json()["user"]["id"]


def test_oauth_backfills_pending_meeting_shares(client: TestClient, monkeypatch):
    from infra import identity
    owner = identity.upsert_user_by_supabase("sb-o", "owner@example.com")
    workspaces.add_meeting_share("sess-1", "recipient@example.com", owner["id"])

    # user_id starts NULL on the share row.
    row = _get_conn().execute(
        "SELECT user_id FROM meeting_shares WHERE user_email = ?",
        ("recipient@example.com",),
    ).fetchone()
    assert row["user_id"] is None

    _stub_validate(monkeypatch, email="recipient@example.com", sub="sb-new-user")
    client.post("/auth/v1/exchange-token", json={"access_token": "ok"})

    row = _get_conn().execute(
        "SELECT user_id FROM meeting_shares WHERE user_email = ?",
        ("recipient@example.com",),
    ).fetchone()
    assert row["user_id"] is not None
