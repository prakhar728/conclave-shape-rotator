"""Tests for auth/session.py (token lifecycle) and auth/routes.py (HTTP surface).

Supabase calls (`send_otp`, `verify_otp`) are monkeypatched — these tests
never touch the network. Auth round-trip uses FastAPI's TestClient against
the live app, so cookies + the routers are exercised end-to-end.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from auth import session as auth_session
from infra import identity
from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean_tables():
    """Reset the auth-related tables between tests for isolation."""
    from tests.conftest import reset_workspace_domain_tables
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def user() -> dict:
    return identity.upsert_user_by_supabase("sb-test", "u@example.com", "U")


# ---------------------------------------------------------------------------
# session.py — token lifecycle
# ---------------------------------------------------------------------------


def test_issue_and_resolve_roundtrip(user: dict):
    token = auth_session.issue_session(user["id"])
    assert isinstance(token, str) and len(token) > 32  # url-safe of 32 bytes ~ 43 chars
    row = _get_conn().execute(
        "SELECT user_id FROM sessions WHERE token = ?", (token,)
    ).fetchone()
    assert row["user_id"] == user["id"]
    resolved = auth_session._resolve_token(token)
    assert resolved is not None
    assert resolved["id"] == user["id"]


def test_resolve_unknown_token_returns_none():
    assert auth_session._resolve_token("nope-not-a-real-token") is None


def test_resolve_expired_token_returns_none_and_deletes_row(user: dict):
    # Manually insert an already-expired row to bypass issue_session's TTL.
    past = datetime.utcnow() - timedelta(days=1)
    _get_conn().execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at, last_seen_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("expired-tok", user["id"], past.isoformat() + "Z",
         past.isoformat() + "Z", past.isoformat() + "Z"),
    )
    assert auth_session._resolve_token("expired-tok") is None
    # Lazy cleanup of expired row.
    assert _get_conn().execute(
        "SELECT 1 FROM sessions WHERE token = ?", ("expired-tok",)
    ).fetchone() is None


def test_rolling_refresh_extends_expiry_when_close(user: dict):
    # Insert a row expiring in 3 days — well inside the refresh window (7d).
    soon = datetime.utcnow() + timedelta(days=3)
    _get_conn().execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at, last_seen_at) "
        "VALUES (?, ?, ?, ?, ?)",
        ("rolling-tok", user["id"], datetime.utcnow().isoformat() + "Z",
         soon.isoformat() + "Z", datetime.utcnow().isoformat() + "Z"),
    )
    auth_session._resolve_token("rolling-tok")
    new_expires = _get_conn().execute(
        "SELECT expires_at FROM sessions WHERE token = ?", ("rolling-tok",)
    ).fetchone()["expires_at"]
    # Should have been pushed to ~30 days out.
    extended = datetime.fromisoformat(new_expires.rstrip("Z"))
    assert extended > datetime.utcnow() + timedelta(days=20)


def test_revoke_session_deletes_row(user: dict):
    token = auth_session.issue_session(user["id"])
    auth_session.revoke_session(token)
    assert auth_session._resolve_token(token) is None


def test_orphaned_session_cleans_up_if_user_deleted(user: dict):
    """Defensive branch in _resolve_token — user gone but session still around.

    In practice FK constraints prevent a user row from being deleted while
    a session points at it. We simulate the orphan by toggling FKs off for
    the destructive bit, then back on.
    """
    token = auth_session.issue_session(user["id"])
    conn = _get_conn()
    conn.execute("PRAGMA foreign_keys=OFF")
    try:
        conn.execute("DELETE FROM users WHERE id = ?", (user["id"],))
    finally:
        conn.execute("PRAGMA foreign_keys=ON")
    assert auth_session._resolve_token(token) is None
    # Lazy cleanup of the orphaned session row.
    assert conn.execute(
        "SELECT 1 FROM sessions WHERE token = ?", (token,)
    ).fetchone() is None


# ---------------------------------------------------------------------------
# routes.py — HTTP surface
# ---------------------------------------------------------------------------


@pytest.fixture
def client(monkeypatch) -> TestClient:
    """TestClient with Supabase monkeypatched — verify_otp returns a fake id."""
    from infra import supabase_auth as sb

    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    # Patch on both the module of definition AND auth.routes' bound symbols.
    monkeypatch.setattr(sb, "send_otp", lambda email: None)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    import auth.routes as ar
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(
        ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}"
    )
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)

    from main import app
    return TestClient(app)


def test_send_otp_returns_202(client: TestClient):
    r = client.post("/auth/v1/send-otp", json={"email": "test@example.com"})
    assert r.status_code == 202
    assert r.json() == {"ok": True}


def test_send_otp_validates_email(client: TestClient):
    r = client.post("/auth/v1/send-otp", json={"email": "not-an-email"})
    assert r.status_code == 422


def test_verify_otp_creates_user_workspace_and_cookie(client: TestClient):
    r = client.post(
        "/auth/v1/verify-otp",
        json={"email": "new@example.com", "token": "123456"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["user"]["email"] == "new@example.com"
    assert body["workspace"]["name"] == "Personal"
    # Cookie set.
    assert auth_session.COOKIE_NAME in client.cookies


def test_verify_otp_is_idempotent_on_user(client: TestClient):
    r1 = client.post(
        "/auth/v1/verify-otp",
        json={"email": "repeat@example.com", "token": "111111"},
    )
    r2 = client.post(
        "/auth/v1/verify-otp",
        json={"email": "repeat@example.com", "token": "222222"},
    )
    assert r1.json()["user"]["id"] == r2.json()["user"]["id"]
    assert r1.json()["workspace"]["id"] == r2.json()["workspace"]["id"]


def test_me_requires_auth(client: TestClient):
    r = client.get("/auth/v1/me")
    assert r.status_code == 401


def test_me_returns_user_after_login(client: TestClient):
    client.post(
        "/auth/v1/verify-otp", json={"email": "me@example.com", "token": "999000"}
    )
    r = client.get("/auth/v1/me")
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["email"] == "me@example.com"
    assert body["workspace"]["name"] == "Personal"


def test_logout_clears_session(client: TestClient):
    client.post(
        "/auth/v1/verify-otp", json={"email": "out@example.com", "token": "555000"}
    )
    assert client.get("/auth/v1/me").status_code == 200
    client.post("/auth/v1/logout")
    # Cookie cleared, /me now 401.
    assert client.get("/auth/v1/me").status_code == 401


def test_bearer_token_works_for_non_browser(client: TestClient):
    r = client.post(
        "/auth/v1/verify-otp",
        json={"email": "cli@example.com", "token": "777000"},
    )
    # Pull the token out of the cookie and use it as a bearer.
    token = client.cookies.get(auth_session.COOKIE_NAME)
    assert token
    # Fresh client (no cookie) — just header.
    from main import app
    bare = TestClient(app)
    r2 = bare.get("/auth/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["user"]["email"] == "cli@example.com"


def test_supabase_disabled_returns_503(monkeypatch):
    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: False)
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: False)
    from main import app
    c = TestClient(app)
    r = c.post("/auth/v1/send-otp", json={"email": "x@example.com"})
    assert r.status_code == 503
