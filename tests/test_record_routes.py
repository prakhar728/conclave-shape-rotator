"""HTTP tests for POST /api/workspaces/{id}/record (in-person recording ingress).

The FPM diarize + NEAR Whisper calls are monkeypatched to canned segments, so the
test covers the route contract — auth, the timestamp merge, persistence, the
ingest reuse, idempotency, and the disabled-503 — not the external services. The
background enrichment chain is a no-op (as in test_upload_routes).
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from api.record_routes import build_resolved_speakers, merge_by_timestamp
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


# ── build_resolved_speakers — C3 producer ────────────────────

def test_build_resolved_speakers_c3_shape():
    """Per-speaker C3 entry {voiceprint_id, name, confidence}, keyed by the
    SAME display label merge_by_timestamp assigns (so it joins RawSegment)."""
    out = build_resolved_speakers(_IDENTITY)
    assert out == {
        "alice@x.com": {"voiceprint_id": "vp_a", "name": "alice@x.com", "confidence": None},
        "bob@x.com": {"voiceprint_id": "vp_b", "name": "bob@x.com", "confidence": None},
        "Speaker 3": {"voiceprint_id": "vp_c", "name": None, "confidence": None},
    }
    # Labels match what merge produces — the join invariant.
    assert set(out) == {s["speaker"] for s in merge_by_timestamp(_ASR, _IDENTITY)}


def test_build_resolved_speakers_keeps_only_c3_keys():
    """Never leak engine-private fields (local_speaker / decision) across the
    repo boundary — C3 freezes the value shape to exactly three keys."""
    seg = [{"start": 0.0, "end": 1.0, "name": "X", "voiceprint_id": "vp_x",
            "local_speaker": "s0", "decision": "MATCH", "confidence": 0.8}]
    entry = build_resolved_speakers(seg)["X"]
    assert set(entry) == {"voiceprint_id", "name", "confidence"}


def test_build_resolved_speakers_picks_max_confidence_segment():
    """One entry per voiceprint; the representative confidence is the max seen."""
    segs = [
        {"start": 0.0, "end": 1.0, "voiceprint_id": "vp_x", "name": "X", "confidence": 0.4, "local_speaker": "s0"},
        {"start": 1.0, "end": 2.0, "voiceprint_id": "vp_x", "name": "X", "confidence": 0.9, "local_speaker": "s0"},
    ]
    assert build_resolved_speakers(segs) == {
        "X": {"voiceprint_id": "vp_x", "name": "X", "confidence": 0.9}
    }


def test_build_resolved_speakers_graceful_without_voiceprint():
    """C2-degrade: segments with no voiceprint_id (older FPM / live read-only)
    don't crash; keyed by local_speaker, voiceprint_id stored as None."""
    segs = [{"start": 0.0, "end": 1.0, "name": None, "local_speaker": "s0"}]
    assert build_resolved_speakers(segs) == {
        "Speaker 1": {"voiceprint_id": None, "name": None, "confidence": None}
    }
    assert build_resolved_speakers([]) == {}


# ── /v1/diarize NDJSON parse (C2 consumer, voiceprint_id guarantee) ──

def test_parse_diarize_ndjson_backfills_voiceprint_from_streamed():
    """If FPM's final transcript view is display-only (no voiceprint_id),
    back-fill identity from the best-overlapping streamed line, which C2
    guarantees carries it. Closes the cross-repo final-message ambiguity."""
    from api.record_routes import _parse_diarize_ndjson

    body = "\n".join([
        json.dumps({"start": 0.0, "end": 2.0, "voiceprint_id": "vp_a",
                    "name": "alice@x.com", "confidence": 0.8, "local_speaker": "s0"}),
        json.dumps({"start": 2.0, "end": 4.0, "voiceprint_id": "vp_b",
                    "name": None, "confidence": 0.5, "local_speaker": "s1"}),
        json.dumps({"type": "transcript", "segments": [
            {"start": 0.0, "end": 2.0, "text": "hi", "local_speaker": "s0"},
            {"start": 2.0, "end": 4.0, "text": "yo", "local_speaker": "s1"},
        ]}),
    ])
    segs = _parse_diarize_ndjson(body)
    assert segs[0]["voiceprint_id"] == "vp_a" and segs[0]["name"] == "alice@x.com"
    assert segs[1]["voiceprint_id"] == "vp_b"


def test_parse_diarize_ndjson_keeps_identity_bearing_final():
    """When the final view already carries voiceprint_id it is authoritative —
    never clobbered by the streamed (provisional) value."""
    from api.record_routes import _parse_diarize_ndjson

    body = "\n".join([
        json.dumps({"start": 0.0, "end": 2.0, "voiceprint_id": "vp_stream", "local_speaker": "s0"}),
        json.dumps({"type": "transcript", "segments": [
            {"start": 0.0, "end": 2.0, "voiceprint_id": "vp_final", "name": "X", "confidence": 0.9},
        ]}),
    ])
    assert _parse_diarize_ndjson(body)[0]["voiceprint_id"] == "vp_final"


def test_parse_diarize_ndjson_streamed_only_when_no_final():
    from api.record_routes import _parse_diarize_ndjson

    body = json.dumps({"start": 0.0, "end": 2.0, "voiceprint_id": "vp_a", "local_speaker": "s0"})
    assert _parse_diarize_ndjson(body)[0]["voiceprint_id"] == "vp_a"


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


def test_record_persists_resolved_speakers_c3(client: TestClient, monkeypatch):
    """The recorded meeting's resolved_speakers carries voiceprint_id per C3,
    keyed by the display label, with exactly {voiceprint_id, name, confidence}."""
    _enable_record(monkeypatch)
    _login(client, "alice@example.com")
    wsid = _my_workspace_id(client)
    r = client.post(f"/api/workspaces/{wsid}/record", files=_audio())
    assert r.status_code == 202, r.text
    sid = r.json()["session_id"]

    session = store.load_session(sid)
    rs = session.metadata.resolved_speakers
    assert rs["alice@x.com"] == {"voiceprint_id": "vp_a", "name": "alice@x.com", "confidence": None}
    assert rs["bob@x.com"]["voiceprint_id"] == "vp_b"
    assert rs["Speaker 3"] == {"voiceprint_id": "vp_c", "name": None, "confidence": None}
    for entry in rs.values():
        assert set(entry) == {"voiceprint_id", "name", "confidence"}
    # The display label stays the immutable join key on the raw segments.
    assert [s.speaker for s in session.raw_diarization] == ["alice@x.com", "bob@x.com", "Speaker 3"]


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


# ── Task #12: agenda → raw_intent ────────────────────────────


def test_record_form_intent_lands_on_raw_intent(client: TestClient, monkeypatch):
    """Regression guard for the legacy batch path: the /record Form `intent`
    still lands on session.metadata.raw_intent (record_routes.py)."""
    _enable_record(monkeypatch)
    _login(client, "alice@example.com")
    wsid = _my_workspace_id(client)
    r = client.post(f"/api/workspaces/{wsid}/record",
                    files=_audio(), data={"intent": "kickoff sync"})
    assert r.status_code == 202, r.text
    session = store.load_session(r.json()["session_id"])
    assert session.metadata.raw_intent == "kickoff sync"


def test_record_agenda_stash_roundtrip(client: TestClient):
    """POST /record/agenda stashes the agenda keyed by uid (trimmed)."""
    from infra import inperson_agenda
    _login(client, "alice@example.com")
    wsid = _my_workspace_id(client)
    r = client.post(f"/api/workspaces/{wsid}/record/agenda",
                    json={"uid": "inperson-x", "agenda": "  decide pricing  "})
    assert r.status_code == 204, r.text
    assert inperson_agenda.pop_agenda("inperson-x") == "decide pricing"


def test_record_agenda_nonmember_404(client: TestClient):
    """The stash endpoint is member-gated — a non-member can't write (or even
    confirm the workspace exists), and nothing is stashed."""
    from infra import inperson_agenda
    _login(client, "owner2@example.com")
    wsid = _my_workspace_id(client)
    client.cookies.clear()
    _login(client, "intruder2@example.com")
    r = client.post(f"/api/workspaces/{wsid}/record/agenda",
                    json={"uid": "inperson-y", "agenda": "secret agenda"})
    assert r.status_code == 404  # not 403 — no existence leak
    assert inperson_agenda.pop_agenda("inperson-y") is None
