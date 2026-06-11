"""Step 4 — auto-record toggle + scheduler poller dedup.

Recato's launch_bot and the Google client are monkeypatched. Verifies the
toggle endpoint persists opt-in (and rejects meet-less events), and that the
dispatcher launches due meetings exactly once (dedup against in-flight and
recently-completed invitations) while allowing a fresh attempt after a
failed/old invitation.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
    c = _get_conn()
    c.execute("DELETE FROM bot_invitations")
    c.execute("DELETE FROM google_oauth_tokens")
    c.execute("DELETE FROM calendar_auto_record")
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


def _login_and_connect(client):
    me = client.post("/auth/v1/verify-otp", json={"email": "h@example.com", "token": "0"}).json()
    from infra import google_calendar as gc
    gc.save_tokens(user_id=me["user"]["id"], access_token="acc", refresh_token="ref",
                   expiry="2099-01-01T00:00:00+00:00", scopes="s")
    return me


# --- toggle endpoint ---

def test_toggle_auto_record_on(client, monkeypatch):
    me = _login_and_connect(client)
    from infra import google_calendar as gc, calendar_auto_record as car
    monkeypatch.setattr(gc, "get_event", lambda uid, eid: {
        "id": eid, "meet_code": "abc-defg-hij", "title": "Sync"})
    r = client.post("/api/calendar/events/ev1/auto-record",
                    json={"enabled": True, "workspace_id": me["workspace"]["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["meet_code"] == "abc-defg-hij"
    assert "ev1" in car.enabled_event_ids(me["user"]["id"])


def test_toggle_rejects_event_without_meet(client, monkeypatch):
    me = _login_and_connect(client)
    from infra import google_calendar as gc
    monkeypatch.setattr(gc, "get_event", lambda uid, eid: {"id": eid, "meet_code": None})
    r = client.post("/api/calendar/events/ev2/auto-record",
                    json={"enabled": True, "workspace_id": me["workspace"]["id"]})
    assert r.status_code == 422


def test_toggle_off_does_not_fetch_event(client, monkeypatch):
    me = _login_and_connect(client)
    from infra import google_calendar as gc, calendar_auto_record as car
    car.set_auto_record(user_id=me["user"]["id"], google_event_id="ev1",
                        workspace_id=me["workspace"]["id"], meet_code="abc-defg-hij",
                        enabled=True)

    def _boom(uid, eid):
        raise AssertionError("should not fetch event when disabling")
    monkeypatch.setattr(gc, "get_event", _boom)
    r = client.post("/api/calendar/events/ev1/auto-record",
                    json={"enabled": False, "workspace_id": me["workspace"]["id"]})
    assert r.status_code == 200
    assert "ev1" not in car.enabled_event_ids(me["user"]["id"])


# --- dispatcher dedup (pure logic) ---

@pytest.fixture
def dispatch_setup(client, monkeypatch):
    """A connected user opted into one due meeting; launch_bot is faked."""
    me = _login_and_connect(client)
    user_id = me["user"]["id"]
    ws = me["workspace"]["id"]

    from infra import calendar_auto_record as car, google_calendar as gc, calendar_dispatch as cd
    car.set_auto_record(user_id=user_id, google_event_id="ev1", workspace_id=ws,
                        meet_code="abc-defg-hij", enabled=True)
    monkeypatch.setattr(gc, "list_events", lambda uid, **kw: [{
        "id": "ev1", "meet_code": "abc-defg-hij", "title": "Sync"}])

    calls = []
    monkeypatch.setattr(cd, "launch_bot", lambda **kw: calls.append(kw) or {"id": 7, "status": "joining"})
    return user_id, calls


def test_dispatch_launches_due_meeting(dispatch_setup):
    user_id, calls = dispatch_setup
    from infra import calendar_dispatch as cd, bot_invitations
    now = datetime.now(timezone.utc)
    launched = cd.dispatch_for_user(user_id, now=now)
    assert launched == ["abc-defg-hij"]
    assert len(calls) == 1
    inv = bot_invitations.find_by_meeting("google_meet", "abc-defg-hij")
    assert inv["status"] == "joining"
    assert inv["recato_bot_id"] == 7


def test_dispatch_dedup_inflight(dispatch_setup):
    user_id, calls = dispatch_setup
    from infra import calendar_dispatch as cd
    now = datetime.now(timezone.utc)
    cd.dispatch_for_user(user_id, now=now)        # first launch
    second = cd.dispatch_for_user(user_id, now=now)  # in-flight 'joining' → skip
    assert second == []
    assert len(calls) == 1


def test_dispatch_dedup_recent_completion(dispatch_setup):
    user_id, calls = dispatch_setup
    from infra import calendar_dispatch as cd, bot_invitations
    now = datetime.now(timezone.utc)
    cd.dispatch_for_user(user_id, now=now)
    inv = bot_invitations.find_by_meeting("google_meet", "abc-defg-hij")
    bot_invitations.update_status(inv["id"], "completed", completed=True)
    # Same occurrence, minutes later → recent completion blocks re-dispatch.
    assert cd.dispatch_for_user(user_id, now=now + timedelta(minutes=10)) == []
    assert len(calls) == 1


def test_dispatch_allows_after_old_completion(dispatch_setup):
    user_id, calls = dispatch_setup
    from infra import calendar_dispatch as cd, bot_invitations
    now = datetime.now(timezone.utc)
    cd.dispatch_for_user(user_id, now=now)
    inv = bot_invitations.find_by_meeting("google_meet", "abc-defg-hij")
    bot_invitations.update_status(inv["id"], "completed", completed=True)
    # 3h later (recurring occurrence) → completion is stale, dispatch again.
    later = now + timedelta(hours=3)
    assert cd.dispatch_for_user(user_id, now=later) == ["abc-defg-hij"]
    assert len(calls) == 2


def test_dispatch_failed_launch_marks_invitation(client, monkeypatch):
    me = _login_and_connect(client)
    user_id = me["user"]["id"]
    from infra import calendar_auto_record as car, google_calendar as gc, calendar_dispatch as cd, bot_invitations
    from connectors.recato.launch import RecatoLaunchError
    car.set_auto_record(user_id=user_id, google_event_id="ev1",
                        workspace_id=me["workspace"]["id"], meet_code="abc-defg-hij", enabled=True)
    monkeypatch.setattr(gc, "list_events", lambda uid, **kw: [{
        "id": "ev1", "meet_code": "abc-defg-hij", "title": "Sync"}])

    def _fail(**kw):
        raise RecatoLaunchError("recato down")
    monkeypatch.setattr(cd, "launch_bot", _fail)

    now = datetime.now(timezone.utc)
    assert cd.dispatch_for_user(user_id, now=now) == []
    inv = bot_invitations.find_by_meeting("google_meet", "abc-defg-hij")
    assert inv["status"] == "failed"
