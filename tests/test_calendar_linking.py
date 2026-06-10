"""Step 5 — transcript ↔ calendar event linking + attendee auto-share.

Exercises infra.meeting_calendar_links.link_completed_meeting directly
(the webhook just calls it best-effort). Google's get_event is mocked.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "google_client_id", "cid")
    monkeypatch.setattr(settings, "google_client_secret", "cs")
    monkeypatch.setattr(settings, "google_redirect_uri", "https://app.test/cb")
    monkeypatch.setattr(settings, "token_enc_key", Fernet.generate_key().decode())

    from tests.conftest import reset_workspace_domain_tables
    c = _get_conn()
    c.execute("DELETE FROM google_oauth_tokens")
    c.execute("DELETE FROM calendar_auto_record")
    c.execute("DELETE FROM meeting_calendar_links")
    c.execute("DELETE FROM meeting_shares")
    reset_workspace_domain_tables()

    from infra import identity, workspaces, google_calendar as gc, calendar_auto_record as car
    user = identity.upsert_user_by_supabase(supabase_id="sb-cal", email="host@example.com")
    ws = workspaces.ensure_personal_workspace(user["id"])
    gc.save_tokens(user_id=user["id"], access_token="a", refresh_token="r",
                   expiry="2099-01-01T00:00:00+00:00", scopes="s")
    car.set_auto_record(user_id=user["id"], google_event_id="ev1", workspace_id=ws["id"],
                        meet_code="abc-defg-hij", enabled=True)
    yield user["id"]


def test_link_completed_meeting_writes_link_and_shares(monkeypatch, _setup):
    user_id = _setup
    from infra import google_calendar as gc, meeting_calendar_links as mcl, workspaces

    monkeypatch.setattr(gc, "get_event", lambda uid, eid: {
        "id": "ev1", "title": "Design review",
        "start": "2026-06-08T10:00:00Z", "end": "2026-06-08T11:00:00Z",
        "organizer": "host@example.com",
        "attendees": ["host@example.com", "guest@example.com"],
        "meet_code": "abc-defg-hij",
    })

    link = mcl.link_completed_meeting(
        meet_code="abc-defg-hij", session_id="abc-defg-hij", inviter_user_id=user_id)

    assert link is not None
    assert link["title"] == "Design review"
    assert link["google_event_id"] == "ev1"
    assert set(link["attendees"]) == {"host@example.com", "guest@example.com"}

    # attendees auto-shared (keyed by meet code, per the invite-bot convention)
    shares = {s["user_email"] for s in workspaces.list_meeting_shares("abc-defg-hij")}
    assert "guest@example.com" in shares
    assert "host@example.com" in shares


def test_link_noop_when_not_auto_recorded(monkeypatch, _setup):
    from infra import meeting_calendar_links as mcl, google_calendar as gc
    # No calendar_auto_record row for this meet code → returns None, no fetch.
    monkeypatch.setattr(gc, "get_event", lambda uid, eid: (_ for _ in ()).throw(AssertionError("no fetch")))
    assert mcl.link_completed_meeting(
        meet_code="zzz-zzzz-zzz", session_id="zzz-zzzz-zzz", inviter_user_id=None) is None


def test_link_noop_when_event_fetch_fails(monkeypatch, _setup):
    user_id = _setup
    from infra import google_calendar as gc, meeting_calendar_links as mcl

    def _fail(uid, eid):
        raise gc.GoogleCalendarError("event not found")
    monkeypatch.setattr(gc, "get_event", _fail)
    # Resolvable event id but Google errors → best-effort returns None, no raise.
    assert mcl.link_completed_meeting(
        meet_code="abc-defg-hij", session_id="abc-defg-hij", inviter_user_id=user_id) is None
    assert mcl.get_link("abc-defg-hij") is None
