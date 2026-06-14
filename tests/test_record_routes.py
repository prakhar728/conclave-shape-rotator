"""HTTP tests for POST /api/workspaces/{id}/record (in-person recording ingress).

The FPM diarize + NEAR Whisper calls are monkeypatched to canned segments, so the
test covers the route contract — auth, the timestamp merge, persistence, the
ingest reuse, idempotency, and the disabled-503 — not the external services. The
background enrichment chain is a no-op (as in test_upload_routes).
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.record_routes import merge_by_timestamp
from storage.sqlite import _get_conn
from transcripts import store

_ASR = [
    {"start": 0.0, "end": 2.0, "text": "Hey, thanks for joining."},
    {"start": 2.0, "end": 4.0, "text": "Of course, happy to be here."},
    {"start": 4.0, "end": 6.0, "text": "I'm new, just sitting in."},
]
_IDENTITY = [
    {"start": 0.0, "end": 2.0, "name": "alice@x.com", "local_speaker": "speaker0", "voiceprint_id": "vp_a"},
    {"start": 2.0, "end": 4.0, "name": "bob@x.com", "local_speaker": "speaker1", "voiceprint_id": "vp_b"},
    {"start": 4.0, "end": 6.0, "name": None, "local_speaker": "speaker2", "voiceprint_id": "vp_c"},
]


# ── pure merge unit ──────────────────────────────────────────

def test_merge_named_and_anonymous():
    out = merge_by_timestamp(_ASR, _IDENTITY)
    assert [s["speaker"] for s in out] == ["alice@x.com", "bob@x.com", "Speaker 3"]
    assert out[0]["text"] == "Hey, thanks for joining."


def test_merge_no_identity_falls_back_to_single_speaker():
    out = merge_by_timestamp(_ASR, [])
    assert {s["speaker"] for s in out} == {"Speaker 1"}


def test_merge_drops_empty_text():
    out = merge_by_timestamp([{"start": 0, "end": 1, "text": "  "}], _IDENTITY)
    assert out == []


def test_merge_numbering_deterministic_independent_of_segment_order():
    """Speaker N must be stable when identity segments arrive in a different
    order (the live vs post passes don't agree on first-appearance order).
    Numbering keys off voiceprint_id, not arrival order."""
    out_fwd = merge_by_timestamp(_ASR, _IDENTITY)
    out_rev = merge_by_timestamp(_ASR, list(reversed(_IDENTITY)))
    assert [s["speaker"] for s in out_fwd] == [s["speaker"] for s in out_rev]
    # vp_a < vp_b < vp_c → the anonymous one (vp_c) is the 3rd voiceprint.
    assert out_fwd[2]["speaker"] == "Speaker 3"


def test_merge_anonymous_numbered_by_sorted_voiceprint_id():
    """All-anonymous speakers are numbered by sorted voiceprint_id, so the
    same set of voiceprints always yields the same Speaker N."""
    anon = [
        {"start": 0.0, "end": 2.0, "name": None, "local_speaker": "s0", "voiceprint_id": "vp_z"},
        {"start": 2.0, "end": 4.0, "name": None, "local_speaker": "s1", "voiceprint_id": "vp_a"},
    ]
    asr = [{"start": 0.0, "end": 2.0, "text": "first"},
           {"start": 2.0, "end": 4.0, "text": "second"}]
    out = merge_by_timestamp(asr, anon)
    # sorted: vp_a=1, vp_z=2 → the vp_z window is Speaker 2, the vp_a window Speaker 1.
    assert out[0]["speaker"] == "Speaker 2"
    assert out[1]["speaker"] == "Speaker 1"


# ── route contract ───────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_tables():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions WHERE session_id LIKE 'upload-%'")
    reset_workspace_domain_tables()
    yield


@pytest.fixture(autouse=True)
def _no_background_enrich(monkeypatch):
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


def _enable_record(monkeypatch, identity=_IDENTITY, asr=_ASR):
    """Turn the feature on and stub the two external calls."""
    from config import settings
    monkeypatch.setattr(settings, "fpm_base_url", "http://fpm.test")
    monkeypatch.setattr(settings, "transcription_service_url", "http://asr.test")
    import api.record_routes as rr

    async def fake_diarize(*a, **k):
        return identity

    async def fake_transcribe(*a, **k):
        return asr

    monkeypatch.setattr(rr, "_fpm_diarize", fake_diarize)
    monkeypatch.setattr(rr, "_transcribe", fake_transcribe)


def _login(client: TestClient, email: str) -> None:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text


def _my_workspace_id(client: TestClient) -> str:
    return client.get("/api/workspaces").json()["workspaces"][0]["id"]


def _audio():
    return {"file": ("rec.webm", b"\x00\x01\x02fakeaudio", "audio/webm")}


def test_unauthenticated_401(client: TestClient):
    r = client.post("/api/workspaces/w/record", files=_audio())
    assert r.status_code == 401


def test_disabled_503(client: TestClient, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "fpm_base_url", "")
    monkeypatch.setattr(settings, "transcription_service_url", "")
    _login(client, "alice@example.com")
    wsid = _my_workspace_id(client)
    r = client.post(f"/api/workspaces/{wsid}/record", files=_audio())
    assert r.status_code == 503


def test_record_happy_path_persists_identified_transcript(client: TestClient, monkeypatch):
    _enable_record(monkeypatch)
    _login(client, "alice@example.com")
    wsid = _my_workspace_id(client)
    r = client.post(f"/api/workspaces/{wsid}/record",
                    files=_audio(), data={"intent": "kickoff sync"})
    assert r.status_code == 202, r.text
    body = r.json()
    sid = body["session_id"]
    assert body["is_processing"] is True
    assert set(body["speakers"]) == {"alice@x.com", "bob@x.com", "Speaker 3"}

    session = store.load_session(sid)
    assert session is not None
    speakers = [seg.speaker for seg in session.raw_diarization]
    assert speakers == ["alice@x.com", "bob@x.com", "Speaker 3"]
    fields = store.get_workspace_fields(sid)
    assert fields["workspace_id"] == wsid and fields["visibility"] == "owner-only"


def test_record_nonmember_404(client: TestClient, monkeypatch):
    _enable_record(monkeypatch)
    _login(client, "owner@example.com")
    wsid = _my_workspace_id(client)
    client.cookies.clear()
    _login(client, "intruder@example.com")
    r = client.post(f"/api/workspaces/{wsid}/record", files=_audio())
    assert r.status_code == 404  # not 403 — no existence leak


def test_record_empty_audio_400(client: TestClient, monkeypatch):
    _enable_record(monkeypatch)
    _login(client, "alice@example.com")
    wsid = _my_workspace_id(client)
    r = client.post(f"/api/workspaces/{wsid}/record",
                    files={"file": ("rec.webm", b"", "audio/webm")})
    assert r.status_code == 400
