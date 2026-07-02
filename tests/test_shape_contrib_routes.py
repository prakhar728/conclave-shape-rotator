"""Route tests for POST /api/meetings/{id}/contribute-shapeos (Task #20, Arm 1).

Harness mirrors test_approve_endpoint.py. Runs with dry-run ON so the real
contribute_raw executes (building + validating the payload) but never touches the
network. Asserts the two server-side gates (owner-only + v2-approved) and the
happy path.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from config import settings
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


@pytest.fixture(autouse=True)
def _dry_run(monkeypatch):
    # Safety: every route test runs with the network-skipping dry-run valve ON.
    monkeypatch.setattr(settings, "shapeos_contrib_dry_run", True)
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


def _wsid(client):
    return client.get("/api/workspaces").json()["workspaces"][0]["id"]


def _make_session(sid, wsid, owner_id):
    store.save_session(
        Session(
            session_id=sid,
            raw_diarization=[RawSegment(speaker="speaker_1", text="hello world")],
            metadata=SessionMetadata(date="2026-06-29", source="test"),
        )
    )
    store.set_workspace(sid, workspace_id=wsid, owner_user_id=owner_id, visibility="owner-only")


URL = "/api/meetings/{}/contribute-shapeos"


def test_requires_auth(client):
    assert client.post(URL.format("nope")).status_code == 401


def test_404_when_no_session(client):
    _login(client)
    assert client.post(URL.format("ghost")).status_code == 404


def test_non_owner_cannot_contribute(client):
    owner = _login(client, "owner@example.com")
    wsid = _wsid(client)
    _make_session("m1", wsid, owner["id"])
    store.create_v2_draft("m1")
    store.approve_v2("m1")
    _login(client, "intruder@example.com")  # switch user
    assert client.post(URL.format("m1")).status_code == 403


def test_409_when_v2_not_approved(client):
    user = _login(client)
    wsid = _wsid(client)
    _make_session("m2", wsid, user["id"])
    store.create_v2_draft("m2")  # draft, NOT approved
    r = client.post(URL.format("m2"))
    assert r.status_code == 409
    assert "approve" in r.json()["detail"].lower()


def test_409_when_no_v2_draft(client):
    user = _login(client)
    wsid = _wsid(client)
    _make_session("m3", wsid, user["id"])  # no v2 at all
    assert client.post(URL.format("m3")).status_code == 409


def test_happy_path_posts_inbox_dry_run(client):
    user = _login(client)
    wsid = _wsid(client)
    _make_session("m4", wsid, user["id"])
    store.create_v2_draft("m4")
    store.approve_v2("m4")
    r = client.post(URL.format("m4"))
    assert r.status_code == 200, r.text
    inbox = r.json()["inbox"]
    assert inbox["ok"] is True
    assert inbox["status"] == "dry_run"
    assert inbox["parts"] == 1


def test_real_post_path_is_gated_behind_dry_run(client, monkeypatch):
    # With dry-run OFF, the endpoint calls contribute_raw for real — assert it
    # routes through our injected client (still no real network: we stub post).
    monkeypatch.setattr(settings, "shapeos_contrib_dry_run", False)
    captured = {}
    from infra import shape_contrib as sc

    def fake_contribute_raw(**kwargs):
        captured.update(kwargs)
        return sc.InboxResult(ok=True, status="ok", parts=1, http_statuses=[201])

    monkeypatch.setattr(sc, "contribute_raw", fake_contribute_raw)
    user = _login(client)
    wsid = _wsid(client)
    _make_session("m5", wsid, user["id"])
    store.create_v2_draft("m5")
    store.approve_v2("m5")
    r = client.post(URL.format("m5"))
    assert r.status_code == 200, r.text
    assert r.json()["inbox"]["status"] == "ok"
    # Built from the approved v2 + carries provenance.
    assert captured["metadata"]["conclave_session_id"] == "m5"
    assert captured["metadata"]["workspace_id"] == wsid
    assert captured["url"] == settings.shapeos_supabase_url
    assert captured["segments"]  # non-empty corrected transcript


def _capture_contribute(monkeypatch):
    """Stub contribute_raw, returning a dict the test fills with the call kwargs."""
    monkeypatch.setattr(settings, "shapeos_contrib_dry_run", False)
    captured: dict = {}
    from infra import shape_contrib as sc

    def fake(**kwargs):
        captured.update(kwargs)
        return sc.InboxResult(ok=True, status="ok", parts=1, http_statuses=[201])

    monkeypatch.setattr(sc, "contribute_raw", fake)
    return captured


def test_agenda_flows_into_submission_metadata(client, monkeypatch):
    # Task #12 agenda (metadata.raw_intent) rides into the Shape OS submission,
    # trimmed. "raw transcript + agenda → Shape" is then literal.
    captured = _capture_contribute(monkeypatch)
    user = _login(client)
    wsid = _wsid(client)
    store.save_session(
        Session(
            session_id="m6",
            raw_diarization=[RawSegment(speaker="speaker_1", text="hello world")],
            metadata=SessionMetadata(date="2026-06-29", source="test", raw_intent="  Decide Q3 roadmap  "),
        )
    )
    store.set_workspace("m6", workspace_id=wsid, owner_user_id=user["id"], visibility="owner-only")
    store.create_v2_draft("m6")
    store.approve_v2("m6")
    r = client.post(URL.format("m6"))
    assert r.status_code == 200, r.text
    assert captured["metadata"]["agenda"] == "Decide Q3 roadmap"  # trimmed


def test_no_agenda_key_when_absent(client, monkeypatch):
    # No agenda stashed → no `agenda` key (never a null/empty field on the row).
    captured = _capture_contribute(monkeypatch)
    user = _login(client)
    wsid = _wsid(client)
    _make_session("m7", wsid, user["id"])  # SessionMetadata has no raw_intent
    store.create_v2_draft("m7")
    store.approve_v2("m7")
    r = client.post(URL.format("m7"))
    assert r.status_code == 200, r.text
    assert "agenda" not in captured["metadata"]
