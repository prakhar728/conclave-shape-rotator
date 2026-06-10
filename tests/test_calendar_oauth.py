"""Step 2 — dedicated Google OAuth flow.

Google's token endpoint is monkeypatched (no network). Verifies the connect
URL is well-formed, the callback exchanges + stores encrypted tokens keyed
to the state's user, status reflects connect/disconnect, state tampering is
rejected, and the whole surface 503s when unconfigured.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from storage.sqlite import _get_conn


def _configure(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "google_client_id", "cid.apps.googleusercontent.com")
    monkeypatch.setattr(settings, "google_client_secret", "csecret")
    monkeypatch.setattr(settings, "google_redirect_uri", "https://app.test/api/calendar/callback")
    monkeypatch.setattr(settings, "token_enc_key", Fernet.generate_key().decode())


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM google_oauth_tokens")
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def client(monkeypatch) -> TestClient:
    _configure(monkeypatch)
    # Supabase auth shim (same pattern as test_bot_routes).
    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "send_otp", lambda email: None)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    from main import app
    return TestClient(app, follow_redirects=False)


def _login(client: TestClient, email: str = "host@example.com") -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return r.json()


def test_unconfigured_returns_503(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")
    monkeypatch.setattr(settings, "google_redirect_uri", "")
    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    from main import app
    c = TestClient(app)
    c.post("/auth/v1/verify-otp", json={"email": "x@example.com", "token": "0"})
    assert c.get("/api/calendar/status").status_code == 503


def test_connect_returns_auth_url(client):
    _login(client)
    r = client.get("/api/calendar/connect")
    assert r.status_code == 200, r.text
    url = r.json()["auth_url"]
    assert url.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    assert "access_type=offline" in url
    assert "prompt=consent" in url
    assert "state=" in url


def test_connect_requires_auth(client):
    assert client.get("/api/calendar/connect").status_code == 401


def test_callback_exchanges_and_stores_tokens(client, monkeypatch):
    me = _login(client)
    user_id = me["user"]["id"]

    # Mint a state the same way /connect would.
    from infra import google_calendar as gc
    state = gc.make_state(user_id)

    monkeypatch.setattr(gc, "exchange_code", lambda code: {
        "access_token": "acc-xyz",
        "refresh_token": "ref-xyz",
        "expiry": "2026-06-08T13:00:00+00:00",
        "scope": "calendar.events calendar.readonly",
    })

    r = client.get(f"/api/calendar/callback?code=authcode&state={state}")
    assert r.status_code == 302
    assert "calendar=connected" in r.headers["location"]

    stored = gc.get_tokens(user_id)
    assert stored["access_token"] == "acc-xyz"
    assert stored["refresh_token"] == "ref-xyz"

    # status now reports connected
    s = client.get("/api/calendar/status")
    assert s.json()["connected"] is True


def test_callback_rejects_tampered_state(client):
    _login(client)
    r = client.get("/api/calendar/callback?code=authcode&state=bogus.deadbeef")
    assert r.status_code == 400


def test_callback_denied_redirects(client):
    _login(client)
    from infra import google_calendar as gc
    state = gc.make_state("whoever")
    r = client.get(f"/api/calendar/callback?state={state}&error=access_denied")
    assert r.status_code == 302
    assert "calendar=denied" in r.headers["location"]


def test_disconnect(client, monkeypatch):
    me = _login(client)
    user_id = me["user"]["id"]
    from infra import google_calendar as gc
    gc.save_tokens(user_id=user_id, access_token="a", refresh_token="r",
                   expiry=None, scopes="")
    r = client.post("/api/calendar/disconnect")
    assert r.status_code == 200
    assert client.get("/api/calendar/status").json()["connected"] is False


def test_valid_access_token_refreshes_when_expired(client, monkeypatch):
    me = _login(client)
    user_id = me["user"]["id"]
    from infra import google_calendar as gc
    # Stored token already expired.
    gc.save_tokens(user_id=user_id, access_token="old", refresh_token="ref-1",
                   expiry="2000-01-01T00:00:00+00:00", scopes="s")
    monkeypatch.setattr(gc, "refresh_access_token", lambda rt: {
        "access_token": "fresh", "expiry": "2099-01-01T00:00:00+00:00",
    })
    assert gc.valid_access_token(user_id) == "fresh"
    # refresh token preserved
    assert gc.get_tokens(user_id)["refresh_token"] == "ref-1"
