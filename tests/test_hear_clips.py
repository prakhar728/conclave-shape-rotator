"""Task #3 (Conclave side) — Proposed→Confirm, hear-the-clip capability, recognition notices.

  (a) a not-yet-consented MATCH surfaces as `proposed_name` (host one-click confirm), NOT a
      silently-applied name; a consented MATCH auto-applies. Recognition alone never proposes.
  (b) tag/confirm attaches a representative clip_ref; the #30 audio endpoint serves the clip
      to a non-member subject holding a valid FPM-signed capability (expiring, session-bound).
  (c) after finalize, each recognized voiceprint is handed to FPM for a transparency notice.
"""
from __future__ import annotations

import base64
import hashlib
import io
import json
import time
import wave

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

# Reuse Task #30's audio fixtures/helpers (client + on-disk encrypted audio).
from tests.test_audio_storage import (  # noqa: F401 — fixtures used by tests
    _audio_env,
    _clean,
    client,
    _make_owned_session,
    _post_chunk,
    _wav_bytes,
)


# ── ed25519 capability minting (mirrors FPM's ReceiptSigner byte-for-byte) ──

_SEED = bytes(range(32))


def _priv(seed: bytes = _SEED) -> Ed25519PrivateKey:
    return Ed25519PrivateKey.from_private_bytes(seed)


def _pub_hex(seed: bytes = _SEED) -> str:
    raw = _priv(seed).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return raw.hex()


def _canon(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _mint_cap(clip_ref: dict, *, sub="alice@x.com", exp=None, purpose="clip-cap",
              seed: bytes = _SEED, tamper=False) -> str:
    raw_pub = _priv(seed).public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = hashlib.sha256(raw_pub).hexdigest()[:16]
    payload = {"purpose": purpose, "clip_ref": clip_ref, "sub": sub,
               "exp": exp if exp is not None else int(time.time()) + 300,
               "alg": "ed25519", "key_id": key_id}
    sig_b64 = base64.b64encode(_priv(seed).sign(_canon(payload))).decode()
    if tamper:
        # Flip a byte INSIDE the signature (envelope still decodes) so the corrupted token
        # actually reaches — and fails — Ed25519 verification, not the envelope-shape check.
        i = 10
        repl = "B" if sig_b64[i] != "B" else "C"
        sig_b64 = sig_b64[:i] + repl + sig_b64[i + 1:]
    env = {"payload": payload, "signature": sig_b64, "alg": "ed25519", "key_id": key_id}
    return base64.urlsafe_b64encode(json.dumps(env, separators=(",", ":")).encode()).decode().rstrip("=")


# ── Part (a): representative clip + Proposed/consented projection ──

def test_representative_clip_picks_longest_segment():
    from api.record_routes import _representative_clip
    from transcripts.models import RawSegment, Session, SessionMetadata, Derived

    sess = Session(
        session_id="s1",
        raw_diarization=[
            RawSegment(speaker="Speaker 1", text="a", start=0.0, end=1.0),
            RawSegment(speaker="Speaker 1", text="b", start=2.0, end=6.0),   # longest
            RawSegment(speaker="Speaker 2", text="c", start=1.0, end=1.5),
        ],
        metadata=SessionMetadata(date="2026-06-30", source="record"),
        derived=Derived(summary="d"),
    )
    clip = _representative_clip(sess, "Speaker 1", "s1")
    assert clip == {"conclave_session_id": "s1", "native_meeting_id": "s1", "start": 2.0, "end": 6.0}
    assert _representative_clip(sess, "Nobody", "s1") is None


# helpers for the read-path projection tests (backstop-style)

def _login_be(client, email="alice@example.com"):
    from infra import identity
    assert client.post("/auth/v1/verify-otp", json={"email": email, "token": "0"}).status_code == 200
    return identity.upsert_user_by_supabase(f"sb-{email}", email)


def _make_session(sid, wsid, owner_id, resolved):
    from transcripts import store
    from transcripts.models import Derived, RawSegment, Session, SessionMetadata
    raw = [RawSegment(speaker=lbl, text=f"{lbl}: hi", start=0.0, end=1.0) for lbl in resolved]
    sess = Session(session_id=sid, raw_diarization=raw,
                   metadata=SessionMetadata(date="2026-06-30", source="record", resolved_speakers=resolved),
                   derived=Derived(summary="d"))
    store.save_session(sess)
    store.set_workspace(sid, workspace_id=wsid, owner_user_id=owner_id, visibility="owner-only")


def _stub_resolve(monkeypatch, mapping):
    import infra.fpm_consent as fc
    monkeypatch.setattr(fc, "consent_resolve_batch_sync", lambda ws, vids, host_user=None: mapping)


def test_unclaimed_match_is_proposed_not_applied(client, monkeypatch):
    user = _login_be(client)
    wsid = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    _make_session("hc-a", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_u", "name": None, "confidence": 0.9}})
    # recognized + named but NOT owner-claimed → consented False
    _stub_resolve(monkeypatch, {"vp_u": {"name": "Alice", "owner_email": None,
                                         "visibility": "named", "consented": False}})
    seg = client.get("/transcripts/sessions/hc-a/transcript").json()["segments"][0]
    assert seg["speaker_name"] is None          # NOT silently applied
    assert seg["proposed_name"] == "Alice"      # shown to host as a one-click confirm
    assert seg["consented"] is False and seg["voiceprint_id"] == "vp_u"


def test_consented_match_auto_applies(client, monkeypatch):
    user = _login_be(client)
    wsid = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    _make_session("hc-b", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_c", "name": None, "confidence": 0.9}})
    _stub_resolve(monkeypatch, {"vp_c": {"name": "Bob", "owner_email": "bob@x.com",
                                         "visibility": "named", "consented": True}})
    seg = client.get("/transcripts/sessions/hc-b/transcript").json()["segments"][0]
    assert seg["speaker_name"] == "Bob" and seg["proposed_name"] is None and seg["consented"] is True


def test_recognition_alone_never_proposes(client, monkeypatch):
    """INVARIANT: rendering a Proposed suggestion never calls propose_binding (anti-spam)."""
    import infra.fpm_consent as fc
    calls = []

    async def _spy(*a, **k):
        calls.append((a, k))
        return {}
    monkeypatch.setattr(fc, "propose_binding", _spy)

    user = _login_be(client)
    wsid = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    _make_session("hc-inv", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_u", "name": None, "confidence": 0.9}})
    _stub_resolve(monkeypatch, {"vp_u": {"name": "Alice", "owner_email": None,
                                         "visibility": "named", "consented": False}})
    r = client.get("/transcripts/sessions/hc-inv/transcript")
    assert r.status_code == 200 and r.json()["segments"][0]["proposed_name"] == "Alice"
    assert calls == []   # recognition surfaced a suggestion but proposed nothing


# ── Part (b): tag_speaker attaches clip_ref; capability serving ──

def test_tag_speaker_attaches_clip_ref(client, monkeypatch):
    import infra.fpm_consent as fc
    from transcripts import store
    from transcripts.models import Derived, RawSegment, Session, SessionMetadata

    captured = {}

    async def _spy(workspace, vid, **kw):
        captured["vid"] = vid
        captured.update(kw)
        return {"status": "pending", "name": None, "proposal_id": "prop_1"}
    monkeypatch.setattr(fc, "propose_binding", _spy)

    me = _login_be(client)
    wsid = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    sess = Session(
        session_id="hc-tag",
        raw_diarization=[
            RawSegment(speaker="Speaker 1", text="hi", start=0.0, end=1.0),
            RawSegment(speaker="Speaker 1", text="lots", start=3.0, end=9.0),  # longest
        ],
        metadata=SessionMetadata(date="2026-06-30", source="record",
                                 resolved_speakers={"Speaker 1": {"voiceprint_id": "vp_t",
                                                                  "name": None, "confidence": 0.77}}),
        derived=Derived(summary="d"))
    store.save_session(sess)
    store.set_workspace("hc-tag", workspace_id=wsid, owner_user_id=me["id"], visibility="owner-only")

    r = client.post(f"/api/workspaces/{wsid}/meetings/hc-tag/tag-speaker",
                    json={"label": "Speaker 1", "name": "Alice", "email": "alice@x.com"})
    assert r.status_code == 200, r.text
    assert captured["clip_ref"] == {"conclave_session_id": "hc-tag", "native_meeting_id": "hc-tag",
                                    "start": 3.0, "end": 9.0}
    assert captured["source"] == "tag" and captured["confidence"] == 0.77


class TestCapabilityServing:
    def _setup(self, client, monkeypatch, sid="hc-clip", seconds=1.0):
        _make_owned_session(client, "owner@x.com", sid)
        _post_chunk(client, sid, _wav_bytes(seconds))
        from config import settings
        monkeypatch.setattr(settings, "fpm_receipt_pubkey_hex", _pub_hex())
        return sid

    def _clip(self, sid, start=0.25, end=0.5):
        return {"conclave_session_id": sid, "native_meeting_id": sid, "start": start, "end": end}

    def test_valid_capability_serves_slice_to_nonmember(self, client, monkeypatch):
        from main import app
        from fastapi.testclient import TestClient
        sid = self._setup(client, monkeypatch)
        cap = _mint_cap(self._clip(sid, 0.25, 0.5))
        anon = TestClient(app)  # no cookie → a non-member subject
        r = anon.get(f"/transcripts/sessions/{sid}/audio?start=0.25&end=0.5&cap={cap}")
        assert r.status_code == 200 and r.headers["content-type"].startswith("audio/wav")
        with wave.open(io.BytesIO(r.content), "rb") as w:
            assert w.getnframes() == 4000  # (0.5-0.25)*16000 — the capability's bounded slice

    def test_expired_capability_rejected(self, client, monkeypatch):
        from main import app
        from fastapi.testclient import TestClient
        sid = self._setup(client, monkeypatch)
        cap = _mint_cap(self._clip(sid), exp=int(time.time()) - 5)
        r = TestClient(app).get(f"/transcripts/sessions/{sid}/audio?cap={cap}")
        assert r.status_code == 403

    def test_tampered_capability_rejected(self, client, monkeypatch):
        from main import app
        from fastapi.testclient import TestClient
        sid = self._setup(client, monkeypatch)
        cap = _mint_cap(self._clip(sid), tamper=True)
        r = TestClient(app).get(f"/transcripts/sessions/{sid}/audio?cap={cap}")
        assert r.status_code == 403

    def test_forged_wrong_key_rejected(self, client, monkeypatch):
        from main import app
        from fastapi.testclient import TestClient
        sid = self._setup(client, monkeypatch)
        cap = _mint_cap(self._clip(sid), seed=bytes([9]) * 32)  # signed by a key we don't trust
        r = TestClient(app).get(f"/transcripts/sessions/{sid}/audio?cap={cap}")
        assert r.status_code == 403

    def test_capability_bound_to_its_session(self, client, monkeypatch):
        from main import app
        from fastapi.testclient import TestClient
        sid = self._setup(client, monkeypatch)
        cap = _mint_cap(self._clip("some-other-session"))  # valid sig, wrong session
        r = TestClient(app).get(f"/transcripts/sessions/{sid}/audio?cap={cap}")
        assert r.status_code == 403

    def test_wrong_purpose_rejected(self, client, monkeypatch):
        from main import app
        from fastapi.testclient import TestClient
        sid = self._setup(client, monkeypatch)
        cap = _mint_cap(self._clip(sid), purpose="not-a-clip")
        r = TestClient(app).get(f"/transcripts/sessions/{sid}/audio?cap={cap}")
        assert r.status_code == 403


def test_verify_capability_unit(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "fpm_receipt_pubkey_hex", _pub_hex())
    from infra import clip_capability as cc
    clip = {"conclave_session_id": "s", "native_meeting_id": "s", "start": 1.0, "end": 2.0}
    ok = cc.verify_capability(_mint_cap(clip))
    assert ok and ok["clip_ref"] == clip and ok["sub"] == "alice@x.com"
    assert cc.verify_capability(_mint_cap(clip, exp=1)) is None       # expired
    assert cc.verify_capability(_mint_cap(clip, tamper=True)) is None  # tampered
    assert cc.verify_capability("not-a-token") is None
    monkeypatch.setattr(settings, "fpm_receipt_pubkey_hex", "")
    monkeypatch.setattr(settings, "fpm_base_url", "")
    assert cc.verify_capability(_mint_cap(clip)) is None               # no pubkey → no access


# ── Part (c): recognition notices after finalize ──

def test_notify_recognitions_only_for_matches_and_dedups(monkeypatch):
    import asyncio
    import infra.fpm_consent as fc
    calls = []

    async def _rec(workspace, vid, **kw):
        calls.append(vid)
        return {"recorded": True}
    monkeypatch.setattr(fc, "record_recognition", _rec)

    segs = [
        {"voiceprint_id": "vp_a", "name": "Alice"},
        {"voiceprint_id": "vp_a", "name": "Alice"},   # dup → one notice
        {"voiceprint_id": "vp_b", "name": "Bob"},
        {"voiceprint_id": "vp_c", "name": None},       # anonymous → no notice
        {"voiceprint_id": None, "name": "x"},          # no vp → skip
    ]
    n = asyncio.get_event_loop().run_until_complete(
        fc.notify_recognitions("ws", segs, native_meeting_id="m1"))
    assert sorted(calls) == ["vp_a", "vp_b"] and n == 2


def test_notify_recognitions_swallows_errors(monkeypatch):
    import asyncio
    import infra.fpm_consent as fc

    async def _boom(workspace, vid, **kw):
        raise RuntimeError("fpm down")
    monkeypatch.setattr(fc, "record_recognition", _boom)
    # must not raise — finalize continues even if every notice fails
    n = asyncio.get_event_loop().run_until_complete(
        fc.notify_recognitions("ws", [{"voiceprint_id": "vp_a", "name": "Alice"}]))
    assert n == 0
