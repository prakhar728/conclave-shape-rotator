"""Prove the record → refine connection end-to-end.

FPM `/v1/diarize` (who-spoke-when) ∥ Whisper `/v1/audio/transcriptions` (the words) →
`merge_by_timestamp` → `[speaker] text` → the SAME v2 refine editor uploads use. The two
external calls are mocked at the record_routes seams, so this verifies the WHOLE pipe
(diarized audio → editable refine draft) without standing up FPM/Whisper. Run with -s to
see the printed diarized output.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import api.record_routes as rec
import api.transcripts_routes as routes
from config import Settings

# FPM /v1/diarize → two anonymous speakers (names suppressed by consent → Speaker N)
IDENTITY = [
    {"start": 0.0, "end": 3.0, "voiceprint_id": "vp_a", "name": None, "confidence": 0.9, "local_speaker": "spk0"},
    {"start": 3.0, "end": 6.0, "voiceprint_id": "vp_b", "name": None, "confidence": 0.8, "local_speaker": "spk1"},
]
# Whisper → words with timestamps
ASR = [
    {"start": 0.2, "end": 2.8, "text": "we should ship Recato today"},
    {"start": 3.2, "end": 5.5, "text": "sounds good lets review the roadmap"},
]


@pytest.fixture(autouse=True)
def _wired(monkeypatch):
    # record feature ON (class-level patch — the settings instance is not mutable)
    monkeypatch.setattr(Settings, "record_meeting_enabled", lambda self: True)

    async def fake_diarize(client, audio, filename, content_type, fpm_ws, host_user=None):
        return IDENTITY

    async def fake_transcribe(client, audio, filename, content_type):
        return ASR

    monkeypatch.setattr(rec, "_fpm_diarize", fake_diarize)
    monkeypatch.setattr(rec, "_transcribe", fake_transcribe)
    # keep ingest deterministic + offline (no LLM / KB / mail)
    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: True)
    monkeypatch.setattr(routes, "_build_kb", lambda sid: None)
    monkeypatch.setattr(routes, "_send_attendee_magic_links", lambda sid: None)


@pytest.fixture
def client(monkeypatch):
    import auth.routes as ar
    from infra import supabase_auth as sb
    for mod in (sb, ar):
        monkeypatch.setattr(mod, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "send_otp", lambda e: None)
    monkeypatch.setattr(sb, "verify_otp", lambda e, t: f"sb-{e}")
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda e: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda e, t: f"sb-{e}")
    from main import app
    return TestClient(app)


def test_record_produces_diarized_refine_draft(client, monkeypatch):
    real_enrich = routes._enrich_in_background
    monkeypatch.setattr(routes, "_enrich_in_background", lambda sid: None)  # disarm async task

    client.post("/auth/v1/verify-otp", json={"email": "rec@x.com", "token": "0"})
    from infra import identity
    identity.upsert_user_by_supabase("sb-rec@x.com", "rec@x.com")
    ws = client.get("/api/workspaces").json()["workspaces"][0]["id"]

    # --- POST a recording (audio bytes are dummy; FPM + Whisper are mocked) ---
    r = client.post(f"/api/workspaces/{ws}/record",
                    files={"file": ("clip.webm", b"fake-audio-bytes", "audio/webm")})
    assert r.status_code == 202, r.text
    body = r.json()
    sid = body["session_id"]
    print("\n[record] HTTP 202; speakers:", body["speakers"])
    assert body["speakers"] == ["Speaker 1", "Speaker 2"]  # deterministic by sorted voiceprint key

    # --- build the v2 draft (the SAME refine machinery uploads use) ---
    real_enrich(sid)
    v2 = client.get(f"/transcripts/sessions/{sid}/v2").json()
    print("[refine] segments:", [(s["speaker_label"], " ".join(s["tokens"])) for s in v2["segments"]])
    print("[refine] oov:", [a["surface"] for a in v2["annotations"] if a["state"] == "oov"])

    # the diarized recording is now an editable refine draft
    assert v2["status"] == "draft"
    assert [s["speaker_label"] for s in v2["segments"]] == ["Speaker 1", "Speaker 2"]  # diarization kept
    seg0 = " ".join(v2["segments"][0]["tokens"])
    assert "Recato" in seg0  # Whisper words landed, aligned to the right speaker
    assert any(a["surface"] == "Recato" and a["state"] == "oov" for a in v2["annotations"])  # OOV runs

    # FPM voiceprint mapping persisted separately (for later identity), NOT on the text segs
    from transcripts import store
    rs = store.load_session(sid).metadata.resolved_speakers
    print("[identity] resolved_speakers:", rs)
    assert rs["Speaker 1"]["voiceprint_id"] == "vp_a"
    assert rs["Speaker 2"]["voiceprint_id"] == "vp_b"
    print("[✓] record → diarized [speaker] text → editable refine draft\n")
