"""Part 1 increment 6c — editor WRITE API (edit-token / tag-entity / assign-speaker).

The POST surfaces the frontend editor calls. Auth/owner-gated; mutate → persist on
v2. Detection + correction-classify are stubbed (these test HTTP wiring).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra import identity
from transcripts import candidate, store, vocab
from transcripts.models import RawSegment, Session, SessionMetadata


@pytest.fixture(autouse=True)
def _clean():
    from storage.sqlite import _get_conn
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")  # cascades to v2
    reset_workspace_domain_tables()
    yield


@pytest.fixture(autouse=True)
def _no_spacy(monkeypatch):
    monkeypatch.setattr(candidate, "detect", lambda text, user_id: (text.split(), []))
    monkeypatch.setattr(candidate, "classify_correction", lambda t: "text")


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


def _draft(sid, wsid, owner_id):
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="speaker_1", text="we use the DStack protocol")],
        metadata=SessionMetadata(date="2026-06-22", source="test"),
    ))
    store.set_workspace(sid, workspace_id=wsid, owner_user_id=owner_id, visibility="owner-only")
    store.create_v2_draft(sid)


def test_edit_token_owner(client):
    u = _login(client); ws = _wsid(client); _draft("e1", ws, u["id"])
    r = client.post("/transcripts/sessions/e1/v2/edit-token",
                    json={"segment_id": 0, "token_idx": 3, "new_text": "Dstack"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["v2"]["segments"][0]["tokens"][3] == "Dstack"
    assert "decision" in body


def test_tag_entity_writes_vocab(client):
    u = _login(client); ws = _wsid(client); _draft("e2", ws, u["id"])
    r = client.post("/transcripts/sessions/e2/v2/tag-entity",
                    json={"segment_id": 0, "token_start": 3, "token_end": 5,
                          "surface": "DStack protocol", "type": "project"})
    assert r.status_code == 200, r.text
    assert vocab.get(u["id"], "DStack protocol").type == "project"
    assert any(a["source"] == "user" and a["surface"] == "DStack protocol"
               for a in r.json()["v2"]["annotations"])


def test_assign_speaker(client):
    u = _login(client); ws = _wsid(client); _draft("e3", ws, u["id"])
    r = client.post("/transcripts/sessions/e3/v2/assign-speaker",
                    json={"segment_id": 0, "name": "Alice"})
    assert r.status_code == 200, r.text
    assert r.json()["v2"]["segments"][0]["speaker_name"] == "Alice"


def test_requires_auth(client):
    r = client.post("/transcripts/sessions/nope/v2/edit-token",
                    json={"segment_id": 0, "token_idx": 0, "new_text": "x"})
    assert r.status_code == 401


def test_non_owner_cannot_edit(client):
    owner = _login(client, "owner@example.com"); ws = _wsid(client); _draft("e4", ws, owner["id"])
    _login(client, "intruder@example.com")
    r = client.post("/transcripts/sessions/e4/v2/edit-token",
                    json={"segment_id": 0, "token_idx": 0, "new_text": "x"})
    assert r.status_code == 403


def test_edit_after_approve_conflicts(client):
    u = _login(client); ws = _wsid(client); _draft("e5", ws, u["id"])
    store.approve_v2("e5")
    r = client.post("/transcripts/sessions/e5/v2/edit-token",
                    json={"segment_id": 0, "token_idx": 0, "new_text": "x"})
    assert r.status_code == 409


def test_edit_missing_v2_404(client):
    u = _login(client); ws = _wsid(client)
    store.save_session(Session(
        session_id="e6",
        raw_diarization=[RawSegment(speaker="s", text="hi")],
        metadata=SessionMetadata(date="2026-06-22", source="t"),
    ))
    store.set_workspace("e6", workspace_id=ws, owner_user_id=u["id"], visibility="owner-only")
    r = client.post("/transcripts/sessions/e6/v2/edit-token",
                    json={"segment_id": 0, "token_idx": 0, "new_text": "x"})
    assert r.status_code == 404
