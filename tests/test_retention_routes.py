"""HTTP-level tests for the Transcript Saving retention surface (Phase 2):

  - GET/POST /api/users/me/settings (account retention default)
  - POST /api/meetings/{id}/retention (per-meeting override)
  - GET /transcripts/sessions/{id}/transcript returns 410 once purged,
    while a summary_only recipient still gets 403 (never 410).

Auth + seed helpers mirror test_meeting_owner_routes.py.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra import identity, workspaces
from storage import sqlite as _sqlite
from storage.sqlite import _get_conn
from transcripts import store


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


def _seed_meeting(*, owner_email: str, session_id: str = "sess-x") -> dict:
    owner = identity.upsert_user_by_supabase(f"sb-{owner_email}", owner_email)
    ws = workspaces.create_workspace("Personal", owner["id"])
    _sqlite.save_transcript_session(
        session_id=session_id,
        source="recato",
        session_date="2026-06-01",
        raw_diarization=[{"speaker": "A", "text": "raw secret words", "start": 0.0}],
        metadata={"date": "2026-06-01", "source": "recato"},
        derived={"summary": "kept summary"},
    )
    _sqlite.set_transcript_workspace(
        session_id=session_id,
        workspace_id=ws["id"],
        owner_user_id=owner["id"],
        visibility="owner-only",
    )
    return {"owner": owner, "workspace": ws, "session_id": session_id}


# --- Account settings -------------------------------------------------------

def test_settings_round_trip(client: TestClient):
    _login(client, "owner@example.com")
    assert client.get("/api/users/me/settings").json() == {"retention_days": None}

    r = client.post("/api/users/me/settings", json={"retention_days": 30})
    assert r.status_code == 200
    assert r.json() == {"retention_days": 30}
    assert client.get("/api/users/me/settings").json() == {"retention_days": 30}


def test_settings_rejects_non_positive(client: TestClient):
    _login(client, "owner@example.com")
    assert client.post("/api/users/me/settings", json={"retention_days": 0}).status_code == 422


def test_settings_requires_auth(client: TestClient):
    assert client.get("/api/users/me/settings").status_code == 401


# --- Per-meeting override ---------------------------------------------------

def test_meeting_retention_override_round_trip(client: TestClient):
    seed = _seed_meeting(owner_email="owner@example.com")
    _login(client, "owner@example.com")

    r = client.post(f"/api/meetings/{seed['session_id']}/retention",
                    json={"mode": "days", "days": 7})
    assert r.status_code == 200
    assert store.get_workspace_fields(seed["session_id"])["retention_override"] == "7"

    r2 = client.post(f"/api/meetings/{seed['session_id']}/retention",
                     json={"mode": "keep_forever"})
    assert r2.status_code == 200
    assert store.get_workspace_fields(seed["session_id"])["retention_override"] == "keep_forever"

    r3 = client.post(f"/api/meetings/{seed['session_id']}/retention",
                     json={"mode": "inherit"})
    assert r3.status_code == 200
    assert store.get_workspace_fields(seed["session_id"])["retention_override"] is None


def test_meeting_retention_non_owner_blocked(client: TestClient):
    seed = _seed_meeting(owner_email="owner@example.com")
    _login(client, "intruder@example.com")
    r = client.post(f"/api/meetings/{seed['session_id']}/retention",
                    json={"mode": "keep_forever"})
    assert r.status_code == 404


# --- Transcript 410 vs 403 after purge --------------------------------------

def test_transcript_410_after_purge_for_owner(client: TestClient):
    seed = _seed_meeting(owner_email="owner@example.com")
    _login(client, "owner@example.com")
    sid = seed["session_id"]

    # Before purge: owner sees the raw transcript.
    r = client.get(f"/transcripts/sessions/{sid}/transcript")
    assert r.status_code == 200
    assert "raw secret words" in r.text

    # Purge the raw transcript (what the sweep does).
    store.purge_raw(sid)

    r2 = client.get(f"/transcripts/sessions/{sid}/transcript")
    assert r2.status_code == 410
    assert "raw secret words" not in r2.text
    # Summary still available on the detail endpoint.
    detail = client.get(f"/transcripts/sessions/{sid}")
    assert detail.status_code == 200
    assert detail.json()["summary"] == "kept summary"
    assert detail.json()["raw_transcript_deleted"] is True


def test_summary_only_recipient_gets_403_not_410_after_purge(client: TestClient):
    seed = _seed_meeting(owner_email="owner@example.com")
    sid = seed["session_id"]
    # Owner shares summary-only with bob, then flips visibility to shared.
    workspaces.add_meeting_share(sid, "bob@example.com", seed["owner"]["id"], scope="summary_only")
    _sqlite.set_transcript_workspace(
        session_id=sid, workspace_id=seed["workspace"]["id"],
        owner_user_id=seed["owner"]["id"], visibility="shared",
    )
    store.purge_raw(sid)

    _login(client, "bob@example.com")
    r = client.get(f"/transcripts/sessions/{sid}/transcript")
    # Bob was never entitled to raw → 403, NOT 410 (he learns nothing about
    # the transcript's existence/state).
    assert r.status_code == 403
