"""HTTP tests for POST /api/workspaces/{id}/transcripts (transcript upload).

Auth via the real verify-otp flow (Supabase monkeypatched), mirroring
test_kb_routes.py. The background enrichment chain is monkeypatched to a
no-op — these tests cover the route contract (auth, parse, persist,
idempotency), not the LLM pipeline.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from storage.sqlite import _get_conn
from transcripts import store

OTTER_TEXT = """\
Ada Lovelace  0:01
We should ship the importer by Friday.

Grace Hopper  0:14
Agreed. I'll review the parser changes tomorrow.
"""


@pytest.fixture(autouse=True)
def _clean_tables():
    from tests.conftest import reset_workspace_domain_tables
    conn = _get_conn()
    conn.execute(
        "DELETE FROM transcript_sessions WHERE session_id LIKE 'upload-%'"
    )
    reset_workspace_domain_tables()
    yield


@pytest.fixture(autouse=True)
def _no_background_enrich(monkeypatch):
    """Upload must not fire real enrichment (LLM calls) in tests."""
    import api.transcripts_routes as tr
    monkeypatch.setattr(tr, "_enrich_in_background", lambda session_id: None)


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
    assert r.status_code == 200, r.text
    return r.json()


def _my_workspace_id(client: TestClient) -> str:
    return client.get("/api/workspaces").json()["workspaces"][0]["id"]


def test_unauthenticated_401(client: TestClient):
    r = client.post("/api/workspaces/w/transcripts", json={"text": OTTER_TEXT})
    assert r.status_code == 401


def test_nonmember_404(client: TestClient):
    _login(client, "owner@example.com")
    wsid = _my_workspace_id(client)
    client.cookies.clear()
    _login(client, "intruder@example.com")
    r = client.post(
        f"/api/workspaces/{wsid}/transcripts", json={"text": OTTER_TEXT}
    )
    assert r.status_code == 404  # not 403 — no existence leak


def test_upload_happy_path_persists_and_binds(client: TestClient):
    _login(client, "alice@example.com")
    wsid = _my_workspace_id(client)
    r = client.post(
        f"/api/workspaces/{wsid}/transcripts",
        json={"filename": "standup notes.txt", "text": OTTER_TEXT},
    )
    assert r.status_code == 202, r.text
    body = r.json()
    sid = body["session_id"]
    assert body["is_processing"] is True
    assert sid.startswith("upload-")

    session = store.load_session(sid)
    assert session is not None
    assert len(session.raw_diarization) == 2
    assert session.raw_diarization[0].speaker == "Ada Lovelace"

    fields = store.get_workspace_fields(sid)
    assert fields["workspace_id"] == wsid
    assert fields["visibility"] == "owner-only"


def test_reupload_same_text_is_idempotent_200(client: TestClient):
    _login(client, "bob@example.com")
    wsid = _my_workspace_id(client)
    payload = {"filename": "weekly.txt", "text": OTTER_TEXT}
    r1 = client.post(f"/api/workspaces/{wsid}/transcripts", json=payload)
    assert r1.status_code == 202
    r2 = client.post(f"/api/workspaces/{wsid}/transcripts", json=payload)
    assert r2.status_code == 200
    assert r2.json()["session_id"] == r1.json()["session_id"]
    assert r2.json()["status"] == "duplicate"


def test_same_filename_different_workspace_no_collision(client: TestClient):
    """The workspace-scoped session id prevents the cross-tenant dedupe leak."""
    _login(client, "carol@example.com")
    ws_a = _my_workspace_id(client)
    r_a = client.post(
        f"/api/workspaces/{ws_a}/transcripts",
        json={"filename": "notes.txt", "text": OTTER_TEXT},
    )
    client.cookies.clear()
    _login(client, "dave@example.com")
    ws_b = _my_workspace_id(client)
    r_b = client.post(
        f"/api/workspaces/{ws_b}/transcripts",
        json={"filename": "notes.txt", "text": OTTER_TEXT},
    )
    assert r_a.status_code == 202 and r_b.status_code == 202
    assert r_a.json()["session_id"] != r_b.json()["session_id"]


def test_oversize_text_422(client: TestClient):
    _login(client, "erin@example.com")
    wsid = _my_workspace_id(client)
    r = client.post(
        f"/api/workspaces/{wsid}/transcripts",
        json={"text": "x" * (2 * 1024 * 1024 + 1)},
    )
    assert r.status_code == 422


def test_unparseable_text_422_and_not_stored(client: TestClient):
    _login(client, "frank@example.com")
    wsid = _my_workspace_id(client)
    r = client.post(
        f"/api/workspaces/{wsid}/transcripts",
        json={"text": "this is not a transcript at all, no speakers here"},
    )
    assert r.status_code == 422
    assert "could not parse" in r.json()["detail"]
