"""Part 1 increment 7 — suggestion engine (speaker + vocab): SP-1/2/4/7/8, CS-1/3.

Speaker suggestions come ONLY from identity-connected sources (workspace voiceprints
+ this meeting's invitees) — names are NOT mined out of the transcript text. Speaker
warm-path is mocked (the workspace FK makes fabricating real workspaces heavy); the
ranking + cold/empty paths are real.
"""
from __future__ import annotations

from transcripts import store, suggest, vocab
from transcripts.models import RawSegment, Session, SessionMetadata


def _save(sid, *, participants=None, text="hello world", resolved=None):
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="speaker_1", text=text)],
        metadata=SessionMetadata(
            date="2026-06-22", source="t",
            participants=participants, resolved_speakers=resolved or {},
        ),
    ))


def _prior(sid, name):
    return Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="speaker_1", text="x")],
        metadata=SessionMetadata(
            date="2026-06-22", source="t",
            resolved_speakers={"Speaker 1": {"voiceprint_id": "vp", "name": name, "confidence": 0.9}},
        ),
    )


def test_cold_from_invitees():  # SP-2 / CS-1
    _save("sp2", participants=["Alice", "Bob"])
    assert suggest.speaker_suggestions("sp2") == ["Alice", "Bob"]


def test_empty_account_empty():  # SP-7
    _save("sp7")
    assert suggest.speaker_suggestions("sp7") == []


def test_warm_from_workspace(monkeypatch):  # SP-4
    _save("sp4")
    monkeypatch.setattr(store, "get_workspace_fields", lambda sid: {"workspace_id": "ws"})
    monkeypatch.setattr(store, "list_workspace_sessions", lambda wsid: [_prior("prior4", "Carol")])
    assert "Carol" in suggest.speaker_suggestions("sp4")


def test_warm_before_cold(monkeypatch):  # SP-8
    _save("sp8", participants=["Alice"])
    monkeypatch.setattr(store, "get_workspace_fields", lambda sid: {"workspace_id": "ws"})
    monkeypatch.setattr(store, "list_workspace_sessions", lambda wsid: [_prior("prior8", "Carol")])
    sugg = suggest.speaker_suggestions("sp8")
    assert sugg.index("Carol") < sugg.index("Alice")  # warm ranks first


def test_cold_account_no_warm():  # CS-3 / SP-1
    _save("sp1", participants=["Alice"])
    assert suggest.speaker_suggestions("sp1") == ["Alice"]  # only cold; no leakage


def test_text_mentions_not_suggested():  # SP-3 (flipped) — names in the text are NOT mined
    # "Alice" appears in the transcript but is not an invitee or a known voiceprint →
    # it must NOT be suggested. Suggestions come only from workspace/VFTEE identity.
    _save("sp3", text="thanks Alice for the update", participants=None)
    assert suggest.speaker_suggestions("sp3") == []


def test_vocab_autocomplete():  # 7b vocab autocomplete
    vocab.put("uS", "DStack protocol", type="project")
    vocab.put("uS", "Datadog", type="tool")
    vocab.put("uS", "roadmap", type="topic")
    assert suggest.vocab_suggestions("uS", "da") == ["datadog"]
    assert set(suggest.vocab_suggestions("uS", "")) == {"datadog", "dstack protocol", "roadmap"}


# --- GET suggestion endpoints ---

import pytest  # noqa: E402


@pytest.fixture
def client(monkeypatch):
    from fastapi.testclient import TestClient
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


def _login(client, email):
    from infra import identity
    client.post("/auth/v1/verify-otp", json={"email": email, "token": "0"})
    return identity.upsert_user_by_supabase(f"sb-{email}", email)


def test_get_speaker_suggestions_api(client):
    _login(client, "a@x.com")
    _save("api_sp", participants=["Alice", "Bob"])
    r = client.get("/transcripts/sessions/api_sp/suggestions/speakers")
    assert r.status_code == 200, r.text
    assert r.json()["speakers"] == ["Alice", "Bob"]


def test_get_vocab_suggestions_api(client):
    user = _login(client, "b@x.com")
    vocab.put(user["id"], "Datadog", type="tool")
    r = client.get("/transcripts/suggestions/vocab?prefix=da")
    assert r.status_code == 200, r.text
    assert "datadog" in r.json()["vocab"]


def test_speaker_suggestions_requires_auth(client):
    _save("api_noauth", participants=["Alice"])
    assert client.get("/transcripts/sessions/api_noauth/suggestions/speakers").status_code == 401
