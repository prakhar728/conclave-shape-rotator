"""Step 3 — list + create calendar events (Google client mocked).

Covers Meet-code extraction from hangoutLink and conferenceData, event
normalization, the /events listing (with auto_record annotation), and
event creation with a Meet link.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient

from storage.sqlite import _get_conn


def _configure(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "csecret")
    monkeypatch.setattr(settings, "google_redirect_uri", "https://app.test/cb")
    monkeypatch.setattr(settings, "token_enc_key", Fernet.generate_key().decode())


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM google_oauth_tokens")
    _get_conn().execute("DELETE FROM calendar_auto_record")
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def client(monkeypatch) -> TestClient:
    _configure(monkeypatch)
    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    from main import app
    return TestClient(app)


def _login_and_connect(client, monkeypatch):
    r = client.post("/auth/v1/verify-otp", json={"email": "h@example.com", "token": "0"})
    me = r.json()
    from infra import google_calendar as gc
    gc.save_tokens(user_id=me["user"]["id"], access_token="acc",
                   refresh_token="ref", expiry="2099-01-01T00:00:00+00:00", scopes="s")
    return me


# --- unit: meet-code extraction ---

def test_extract_meet_code_from_hangout_link():
    from infra import google_calendar as gc
    assert gc.extract_meet_code({"hangoutLink": "https://meet.google.com/abc-defg-hij"}) == "abc-defg-hij"


def test_extract_meet_code_from_conference_data():
    from infra import google_calendar as gc
    ev = {"conferenceData": {"entryPoints": [
        {"entryPointType": "more", "uri": "https://tel.meet/x"},
        {"entryPointType": "video", "uri": "https://meet.google.com/qwe-rtyu-iop"},
    ]}}
    assert gc.extract_meet_code(ev) == "qwe-rtyu-iop"


def test_extract_meet_code_none_when_absent():
    from infra import google_calendar as gc
    assert gc.extract_meet_code({"summary": "no meet"}) is None


# --- routes ---

def test_list_events_requires_connection(client, monkeypatch):
    client.post("/auth/v1/verify-otp", json={"email": "h@example.com", "token": "0"})
    # connected? no → 409
    r = client.get("/api/calendar/events")
    assert r.status_code == 409


def test_list_events_returns_normalized_with_auto_record(client, monkeypatch):
    me = _login_and_connect(client, monkeypatch)
    from infra import google_calendar as gc, calendar_auto_record as car

    raw = [
        {
            "id": "ev1", "summary": "Standup",
            "start": {"dateTime": "2026-06-08T10:00:00Z"},
            "end": {"dateTime": "2026-06-08T10:15:00Z"},
            "organizer": {"email": "h@example.com"},
            "attendees": [{"email": "a@example.com"}, {"email": "b@example.com"}],
            "hangoutLink": "https://meet.google.com/abc-defg-hij",
            "htmlLink": "https://calendar.google.com/ev1",
        },
        {
            "id": "ev2", "summary": "No-meet block",
            "start": {"dateTime": "2026-06-08T12:00:00Z"},
            "end": {"dateTime": "2026-06-08T13:00:00Z"},
        },
    ]
    monkeypatch.setattr(gc, "list_events", lambda uid, **kw: [gc._normalize_event(e) for e in raw])

    # opt ev1 into auto-record
    ws = me["workspace"]["id"]
    car.set_auto_record(user_id=me["user"]["id"], google_event_id="ev1",
                        workspace_id=ws, meet_code="abc-defg-hij", enabled=True)

    r = client.get("/api/calendar/events")
    assert r.status_code == 200, r.text
    events = r.json()["events"]
    assert events[0]["id"] == "ev1"
    assert events[0]["meet_code"] == "abc-defg-hij"
    assert events[0]["attendees"] == ["a@example.com", "b@example.com"]
    assert events[0]["auto_record"] is True
    assert events[1]["meet_code"] is None
    assert events[1]["auto_record"] is False


def test_create_event_with_meet(client, monkeypatch):
    _login_and_connect(client, monkeypatch)
    from infra import google_calendar as gc

    captured = {}

    def fake_create(uid, **kw):
        captured.update(kw)
        return gc._normalize_event({
            "id": "new1", "summary": kw["title"],
            "start": {"dateTime": kw["start"]}, "end": {"dateTime": kw["end"]},
            "hangoutLink": "https://meet.google.com/new-abcd-efg",
        })

    monkeypatch.setattr(gc, "create_event", fake_create)
    r = client.post("/api/calendar/events", json={
        "title": "Interview w/ candidate",
        "start": "2026-06-09T15:00:00Z",
        "end": "2026-06-09T15:45:00Z",
        "attendees": ["cand@example.com"],
    })
    assert r.status_code == 201, r.text
    ev = r.json()["event"]
    assert ev["title"] == "Interview w/ candidate"
    assert ev["meet_code"] == "new-abcd-efg"
    assert captured["add_meet"] is True
    assert captured["attendees"] == ["cand@example.com"]
