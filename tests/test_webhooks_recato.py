"""Tests for /api/webhooks/recato/meeting-completed.

Recato's fetch is monkeypatched (no network). Enrichment is also stubbed
so the test doesn't hit a real LLM.
"""
from __future__ import annotations

import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from infra import bot_invitations, identity, workspaces
from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")
    _get_conn().execute("DELETE FROM bot_invitations")
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def app_client(monkeypatch) -> TestClient:
    # Stub enrichment so the background task doesn't hit an LLM.
    import api.transcripts_routes as tr
    monkeypatch.setattr(tr, "_enrich_in_background", lambda sid: None)

    # Stub Recato fetch with a minimal Vexa-shape transcript.
    import api.webhooks_recato as wh
    def _fake_fetch(platform, native_id):
        return {
            "id": 999,
            "platform": platform,
            "native_meeting_id": native_id,
            "status": "completed",
            "segments": [
                {
                    "speaker": "Alice",
                    "text": "Hello world",
                    "start": 0.0,
                    "end": 3.0,
                    "absolute_start_time": "2026-06-01T10:00:00Z",
                    "absolute_end_time": "2026-06-01T10:00:03Z",
                    "language": "en",
                },
            ],
            "started_at": "2026-06-01T10:00:00Z",
            "ended_at": "2026-06-01T10:05:00Z",
        }
    monkeypatch.setattr(wh, "_fetch_recato_transcript", _fake_fetch)

    from main import app
    return TestClient(app)


def _event_body(native_id: str = "abc-defg-hij") -> dict:
    return {
        "event_id": "evt_1",
        "event_type": "meeting.completed",
        "api_version": "v1",
        "created_at": "2026-06-01T10:05:00Z",
        "data": {
            "meeting": {
                "id": 999,
                "platform": "google_meet",
                "native_meeting_id": native_id,
                "status": "completed",
            },
        },
    }


def test_unsigned_webhook_accepted_when_secret_unset(app_client: TestClient, monkeypatch):
    monkeypatch.delenv("RECATO_WEBHOOK_SECRET", raising=False)
    r = app_client.post(
        "/api/webhooks/recato/meeting-completed", json=_event_body()
    )
    assert r.status_code == 202
    assert r.json()["status"] == "accepted"


def test_signed_webhook_verified(app_client: TestClient, monkeypatch):
    monkeypatch.setenv("RECATO_WEBHOOK_SECRET", "test-secret")
    body = _event_body()
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(b"test-secret", raw, hashlib.sha256).hexdigest()
    r = app_client.post(
        "/api/webhooks/recato/meeting-completed",
        content=raw,
        headers={"Content-Type": "application/json", "X-Signature": sig},
    )
    assert r.status_code == 202, r.text


def test_bad_signature_401(app_client: TestClient, monkeypatch):
    monkeypatch.setenv("RECATO_WEBHOOK_SECRET", "real-secret")
    body = _event_body()
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(b"wrong", raw, hashlib.sha256).hexdigest()
    r = app_client.post(
        "/api/webhooks/recato/meeting-completed",
        content=raw,
        headers={"Content-Type": "application/json", "X-Signature": sig},
    )
    assert r.status_code == 401


def test_non_completed_event_ignored(app_client: TestClient, monkeypatch):
    monkeypatch.delenv("RECATO_WEBHOOK_SECRET", raising=False)
    body = _event_body()
    body["event_type"] = "meeting.started"
    r = app_client.post(
        "/api/webhooks/recato/meeting-completed", json=body
    )
    assert r.status_code == 202
    assert r.json()["status"] == "ignored"


def test_webhook_binds_workspace_via_invitation(app_client: TestClient, monkeypatch):
    """The whole point of 2.4 — sessions land already-scoped to the inviter."""
    monkeypatch.delenv("RECATO_WEBHOOK_SECRET", raising=False)
    user = identity.upsert_user_by_supabase("sb-host", "host@example.com")
    ws = workspaces.create_workspace("Personal", user["id"])
    bot_invitations.create_invitation(
        user_id=user["id"],
        workspace_id=ws["id"],
        platform="google_meet",
        native_meeting_id="abc-defg-hij",
        status="joining",
        recato_bot_id=999,
    )

    r = app_client.post(
        "/api/webhooks/recato/meeting-completed", json=_event_body()
    )
    assert r.status_code == 202, r.text
    session_id = r.json()["session_id"]

    # Workspace columns populated.
    from storage.sqlite import get_transcript_workspace_fields
    fields = get_transcript_workspace_fields(session_id)
    assert fields["workspace_id"] == ws["id"]
    assert fields["owner_user_id"] == user["id"]
    assert fields["visibility"] == "owner-only"

    # Invitation flipped to 'completed'.
    inv = bot_invitations.find_by_meeting("google_meet", "abc-defg-hij")
    assert inv["status"] == "completed"
    assert inv["completed_at"] is not None


def test_duplicate_webhook_idempotent(app_client: TestClient, monkeypatch):
    monkeypatch.delenv("RECATO_WEBHOOK_SECRET", raising=False)
    r1 = app_client.post(
        "/api/webhooks/recato/meeting-completed", json=_event_body()
    )
    assert r1.status_code == 202
    sid = r1.json()["session_id"]

    r2 = app_client.post(
        "/api/webhooks/recato/meeting-completed", json=_event_body()
    )
    assert r2.status_code == 202
    assert r2.json()["session_id"] == sid
    assert r2.json()["status"] == "duplicate"


def test_empty_transcript_marks_completed_but_no_session(app_client: TestClient, monkeypatch):
    monkeypatch.delenv("RECATO_WEBHOOK_SECRET", raising=False)
    import api.webhooks_recato as wh
    monkeypatch.setattr(wh, "_fetch_recato_transcript", lambda p, n: {"segments": []})

    user = identity.upsert_user_by_supabase("sb-empty", "x@example.com")
    ws = workspaces.create_workspace("WS", user["id"])
    bot_invitations.create_invitation(
        user_id=user["id"],
        workspace_id=ws["id"],
        platform="google_meet",
        native_meeting_id="abc-defg-hij",
        status="joining",
    )

    r = app_client.post(
        "/api/webhooks/recato/meeting-completed", json=_event_body()
    )
    assert r.status_code == 202
    assert r.json()["status"] == "empty_transcript"
    # Invitation still flipped to completed (the meeting is over either way).
    inv = bot_invitations.find_by_meeting("google_meet", "abc-defg-hij")
    assert inv["status"] == "completed"
