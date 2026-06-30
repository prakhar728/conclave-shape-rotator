"""Route tests for POST /api/feedback (Task #19).

Harness mirrors test_shape_contrib_routes.py (Supabase OTP stubbed → cookie auth).
Covers: auth gate, row persistence with server-stamped submitter, category/body
validation, and the best-effort email notify — including that a failing or
unconfigured notify still returns success and still writes the row.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from config import settings
from infra import identity
from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM feedback")
    reset_workspace_domain_tables()
    yield


@pytest.fixture(autouse=True)
def _no_notify(monkeypatch):
    # Default: no team address configured → notify is a no-op. Individual tests
    # opt into a recipient when they want to exercise the email path.
    monkeypatch.setattr(settings, "feedback_notify_email", "")
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


def _login(client, email="alice@example.com"):
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return identity.upsert_user_by_supabase(f"sb-{email}", email)


def _rows():
    return _get_conn().execute(
        "SELECT * FROM feedback ORDER BY created_at"
    ).fetchall()


def test_requires_auth(client):
    r = client.post("/api/feedback", json={"category": "feature", "body": "hi"})
    assert r.status_code == 401


def test_happy_path_persists_row(client):
    user = _login(client)
    r = client.post(
        "/api/feedback",
        json={
            "category": "feature",
            "body": "Add a dark mode please",
            "page_context": "/settings",
        },
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["id"] and out["created_at"]

    rows = _rows()
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == out["id"]
    assert row["category"] == "feature"
    assert row["body"] == "Add a dark mode please"
    assert row["page_context"] == "/settings"
    # Submitter is stamped from the session, not trusted from the client.
    assert row["user_id"] == user["id"]
    assert row["user_email"] == "alice@example.com"


def test_body_is_required(client):
    _login(client)
    r = client.post("/api/feedback", json={"category": "bug", "body": "   "})
    assert r.status_code == 422
    assert _rows() == []


def test_invalid_category_rejected(client):
    _login(client)
    r = client.post("/api/feedback", json={"category": "spam", "body": "hello"})
    assert r.status_code == 422
    assert _rows() == []


def test_page_context_optional(client):
    _login(client)
    r = client.post("/api/feedback", json={"category": "other", "body": "noted"})
    assert r.status_code == 200, r.text
    assert _rows()[0]["page_context"] is None


def test_notify_fires_when_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "feedback_notify_email", "team@conclave.dev")
    calls = []
    import infra.email as email_mod

    def _spy(**kwargs):
        calls.append(kwargs)
        return {"stub": True}

    monkeypatch.setattr(email_mod, "send_feedback_notification", _spy)
    _login(client)
    r = client.post(
        "/api/feedback",
        json={"category": "bug", "body": "crash on save", "page_context": "/meeting/x"},
    )
    assert r.status_code == 200, r.text
    assert len(calls) == 1
    c = calls[0]
    assert c["recipient_email"] == "team@conclave.dev"
    assert c["category"] == "bug"
    assert c["body"] == "crash on save"
    assert c["submitter_email"] == "alice@example.com"
    assert c["page_context"] == "/meeting/x"


def test_submit_succeeds_when_email_fails(client, monkeypatch):
    """Email is best-effort: a raising notify still 200s AND still writes the row."""
    monkeypatch.setattr(settings, "feedback_notify_email", "team@conclave.dev")
    import infra.email as email_mod

    def _boom(**kwargs):
        raise RuntimeError("resend exploded")

    monkeypatch.setattr(email_mod, "send_feedback_notification", _boom)
    _login(client)
    r = client.post("/api/feedback", json={"category": "feature", "body": "still works"})
    assert r.status_code == 200, r.text
    rows = _rows()
    assert len(rows) == 1
    assert rows[0]["body"] == "still works"


# --- Admin read surface: GET /api/feedback -----------------------------------


def _submit(client, **kw):
    payload = {"category": "feature", "body": "x", **kw}
    r = client.post("/api/feedback", json=payload)
    assert r.status_code == 200, r.text
    return r.json()


def test_list_requires_auth(client):
    assert client.get("/api/feedback").status_code == 401


def test_list_forbidden_for_non_admin(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "boss@conclave.dev")
    _login(client, "peon@example.com")  # authed, but not on the allowlist
    r = client.get("/api/feedback")
    assert r.status_code == 403


def test_list_returns_rows_for_admin_newest_first(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "Boss@Conclave.dev")  # case-insensitive
    # A regular user submits two items.
    _login(client, "alice@example.com")
    first = _submit(client, body="older", category="bug")
    second = _submit(client, body="newer", category="feature", page_context="/x")
    # Admin logs in and reads the inbox.
    _login(client, "boss@conclave.dev")
    r = client.get("/api/feedback")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["total"] == 2
    assert out["limit"] == 100 and out["offset"] == 0
    bodies = [i["body"] for i in out["items"]]
    assert bodies == ["newer", "older"]  # newest first
    top = out["items"][0]
    assert top["category"] == "feature"
    assert top["page_context"] == "/x"
    assert top["user_email"] == "alice@example.com"  # the submitter, not the admin


def test_list_pagination(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "boss@conclave.dev")
    _login(client, "alice@example.com")
    for i in range(3):
        _submit(client, body=f"item-{i}")
    _login(client, "boss@conclave.dev")
    r = client.get("/api/feedback?limit=1&offset=1")
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["total"] == 3
    assert len(out["items"]) == 1
    assert out["limit"] == 1 and out["offset"] == 1


def test_no_admin_when_allowlist_empty(client, monkeypatch):
    monkeypatch.setattr(settings, "admin_emails", "")  # nobody is admin
    _login(client, "alice@example.com")
    assert client.get("/api/feedback").status_code == 403


def test_no_notify_attempted_when_unconfigured(client, monkeypatch):
    """With no team address (default), the notify path is not even invoked.

    We assert NON-invocation via a call counter — not by raising from the spy:
    `_notify_team` wraps the send in `except Exception`, which would swallow a
    raised AssertionError and let a removed `if not recipient: return` guard pass
    undetected. A counter is immune to that.
    """
    calls = []
    import infra.email as email_mod

    monkeypatch.setattr(
        email_mod, "send_feedback_notification", lambda **kw: calls.append(kw)
    )
    _login(client)
    r = client.post("/api/feedback", json={"category": "other", "body": "quiet"})
    assert r.status_code == 200, r.text
    assert len(_rows()) == 1
    assert calls == []  # notify never attempted when no recipient is configured
