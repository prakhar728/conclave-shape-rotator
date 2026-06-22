"""Part 1 increment 4b — approve + v2-read API endpoints (G-9 + auth).

Mirrors the auth/client setup in test_tag_speaker.py. The KB stages are spied so
we assert the gate end-to-end (draft → graph empty → approve → build fires).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import transcripts.kb_extract as kbx
import transcripts.kb_pipeline as kbp
from infra import identity
from transcripts import store
from transcripts.models import RawSegment, Session, SessionMetadata


@pytest.fixture(autouse=True)
def _clean():
    from storage.sqlite import _get_conn
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")  # cascades to v2
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


@pytest.fixture
def spies(monkeypatch):
    calls = {"index": 0, "extract": 0}
    monkeypatch.setattr(kbp, "index_session", lambda sid: calls.__setitem__("index", calls["index"] + 1))
    monkeypatch.setattr(kbx, "extract_session", lambda sid: calls.__setitem__("extract", calls["extract"] + 1))
    return calls


def _login(client, email="alice@example.com"):
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return identity.upsert_user_by_supabase(f"sb-{email}", email)


def _wsid(client):
    return client.get("/api/workspaces").json()["workspaces"][0]["id"]


def _make_session(sid, wsid, owner_id):
    store.save_session(
        Session(
            session_id=sid,
            raw_diarization=[RawSegment(speaker="speaker_1", text="hello world")],
            metadata=SessionMetadata(date="2026-06-19", source="test"),
        )
    )
    store.set_workspace(sid, workspace_id=wsid, owner_user_id=owner_id, visibility="owner-only")


def test_get_v2_requires_auth(client):
    assert client.get("/transcripts/sessions/nope/v2").status_code == 401


def test_approve_requires_auth(client):
    assert client.post("/transcripts/sessions/nope/approve").status_code == 401


def test_get_v2_returns_draft(client):
    user = _login(client)
    wsid = _wsid(client)
    _make_session("m1", wsid, user["id"])
    store.create_v2_draft("m1")
    r = client.get("/transcripts/sessions/m1/v2")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "draft"
    assert body["segments"][0]["tokens"] == ["hello", "world"]


def test_approve_runs_build(client, spies):  # G-9
    user = _login(client)
    wsid = _wsid(client)
    _make_session("m2", wsid, user["id"])
    store.create_v2_draft("m2")
    assert spies["index"] == 0  # graph not built yet
    r = client.post("/transcripts/sessions/m2/approve")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "approved"
    assert spies["index"] == 1 and spies["extract"] == 1
    assert store.load_v2("m2").status == "approved"


def test_non_owner_cannot_approve(client, spies):
    owner = _login(client, "owner@example.com")
    wsid = _wsid(client)
    _make_session("m3", wsid, owner["id"])
    store.create_v2_draft("m3")
    _login(client, "intruder@example.com")  # switch to a different user
    r = client.post("/transcripts/sessions/m3/approve")
    assert r.status_code == 403
    assert spies["index"] == 0  # not built


def test_approve_missing_v2_returns_404(client):
    user = _login(client)
    wsid = _wsid(client)
    _make_session("m4", wsid, user["id"])  # no v2 draft
    assert client.post("/transcripts/sessions/m4/approve").status_code == 404
