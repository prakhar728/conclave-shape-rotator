"""Task #30 — audio storage + playback in the TEE (+ capture toggle).

Covers the locked verification checklist (TASK-30 §6):
  1. Toggle OFF (metadata flag / invitation / workspace default) → no file written.
  2. Toggle ON → file written ENCRYPTED (not plaintext-readable on disk) + sha256 recorded.
  3. Decrypt round-trip: full playback + correct `?start=&end=` segment slice.
  4. Legacy plaintext chunks still play (MAGIC-header fallback).
  5. Permission: anon/non-owner can't fetch; owner can.
  6. Deleting audio removes the files (+ flips the read-side store_audio flag).
  7. (mutation seam) flipping the gate / encryption is asserted directly here too.
"""
from __future__ import annotations

import io
import json
import os
import struct
import tempfile
import wave

import pytest
from fastapi.testclient import TestClient

_HEX_KEY = "11" * 32  # 32-byte test master key (non-zero)


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _audio_env(monkeypatch):
    """Point the audio dir + enc key at a fresh temp dir for every test."""
    tmp = tempfile.mkdtemp(prefix="audio-test-")
    monkeypatch.setenv("CONCLAVE_AUDIO_DIR", tmp)
    monkeypatch.setenv("CONCLAVE_AUDIO_ENC_KEY", _HEX_KEY)
    # capture_routes reads _AUDIO_DIR at import time → patch the module global too.
    import api.capture_routes as cr
    monkeypatch.setattr(cr, "_AUDIO_DIR", tmp)
    from config import settings
    monkeypatch.setattr(settings, "audio_enc_key", _HEX_KEY)
    yield tmp


@pytest.fixture(autouse=True)
def _clean():
    from storage.sqlite import _get_conn
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM bot_invitations")
    _get_conn().execute("DELETE FROM transcript_sessions")
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
    import api.bot_routes as br
    monkeypatch.setattr(
        br, "launch_bot",
        lambda **kw: {"id": 7, "status": "joining", "native_meeting_id": kw["native_meeting_id"]},
    )
    from main import app
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return r.json()


def _wav_bytes(seconds: float = 1.0, sr: int = 16000) -> bytes:
    """A mono 16-bit PCM WAV with a deterministic per-frame ramp (so slices differ)."""
    n = int(seconds * sr)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"".join(struct.pack("<h", (i % 1000) - 500) for i in range(n)))
    return buf.getvalue()


def _post_chunk(client: TestClient, meeting_id: str, data: bytes,
                meta_extra: dict | None = None, seq: int = 0):
    meta = {"meeting_id": meeting_id, "format": "wav", **(meta_extra or {})}
    return client.post(
        "/api/capture/audio-chunk",
        files={"file": ("c.wav", data, "audio/wav")},
        data={"metadata": json.dumps(meta), "chunk_seq": str(seq), "is_final": "true"},
    )


def _make_owned_session(client: TestClient, email: str, sid: str):
    """Login + bind a workspace-owned session keyed by `sid` (== audio dir key)."""
    from transcripts import store
    from transcripts.models import Derived, RawSegment, Session, SessionMetadata

    me = _login(client, email)
    uid, ws_id = me["user"]["id"], me["workspace"]["id"]
    sess = Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="A", text="hello", start=0.0, end=1.0)],
        metadata=SessionMetadata(date="2026-06-29", source="capture"),
        derived=Derived(summary="s"),
    )
    store.save_session(sess)
    store.set_workspace(sid, ws_id, uid, visibility="workspace")
    return me, uid, ws_id


# --------------------------------------------------------------------------- #
# 1. Crypto unit
# --------------------------------------------------------------------------- #
class TestCrypto:
    def test_round_trip_and_magic(self):
        from infra import audio_crypto as ac
        pt = b"the quick brown fox" * 100
        blob = ac.encrypt(pt)
        assert ac.is_encrypted(blob)
        assert blob[:4] == b"CAE1"
        assert pt not in blob  # no plaintext leak in the ciphertext
        assert ac.decrypt_if_encrypted(blob) == pt

    def test_legacy_plaintext_passthrough(self):
        from infra import audio_crypto as ac
        legacy = b"RIFFplain-old-wav-bytes"
        assert not ac.is_encrypted(legacy)
        assert ac.decrypt_if_encrypted(legacy) == legacy  # new-only: no retro

    def test_tamper_detected(self):
        from infra import audio_crypto as ac
        blob = bytearray(ac.encrypt(b"secret"))
        blob[-1] ^= 0x01
        with pytest.raises(ValueError):
            ac.decrypt_blob(ac.get_or_create_key(), bytes(blob))

    def test_wrong_key_fails(self):
        from infra import audio_crypto as ac
        blob = ac.encrypt(b"secret audio")
        other = bytes.fromhex("22" * 32)
        with pytest.raises(ValueError):
            ac.decrypt_blob(other, blob)


# --------------------------------------------------------------------------- #
# 2. Encrypt-on-write + sha256 seam
# --------------------------------------------------------------------------- #
class TestEncryptOnWrite:
    def test_written_file_is_encrypted_not_plaintext(self, client, _audio_env):
        pt = _wav_bytes(0.2)
        r = _post_chunk(client, "mtg-enc", pt)
        assert r.status_code == 200, r.text
        assert r.json()["encrypted"] is True

        path = os.path.join(_audio_env, "mtg-enc", "000000.wav")
        on_disk = open(path, "rb").read()
        assert on_disk[:4] == b"CAE1"          # MAGIC header
        assert pt not in on_disk               # NO plaintext at rest
        # sha256 sidecar = hash of the PLAINTEXT (V1 attestation seam)
        import hashlib
        side = open(path + ".sha256").read().strip()
        assert side == hashlib.sha256(pt).hexdigest()

    def test_default_keep_when_no_choice(self, client, _audio_env):
        r = _post_chunk(client, "mtg-default", _wav_bytes(0.1))
        assert r.status_code == 200
        assert os.path.isfile(os.path.join(_audio_env, "mtg-default", "000000.wav"))


# --------------------------------------------------------------------------- #
# 3. store_audio gate (the single enforcement point)
# --------------------------------------------------------------------------- #
class TestStoreAudioGate:
    def test_metadata_flag_false_skips_write(self, client, _audio_env):
        r = _post_chunk(client, "mtg-off", _wav_bytes(0.1),
                        meta_extra={"store_audio": False})
        assert r.status_code == 200
        assert r.json()["status"] == "skipped_no_store"
        assert not os.path.exists(os.path.join(_audio_env, "mtg-off"))

    def test_invitation_false_skips_write(self, client, _audio_env):
        from infra import bot_invitations, identity, workspaces
        u = identity.upsert_user_by_supabase("sb-g", "g@x.com", "G")
        ws = workspaces.create_workspace("P", u["id"])
        bot_invitations.create_invitation(
            user_id=u["id"], workspace_id=ws["id"], platform="google_meet",
            native_meeting_id="meet-off", store_audio=False,
        )
        r = _post_chunk(client, "meet-off", _wav_bytes(0.1))  # no metadata flag
        assert r.json()["status"] == "skipped_no_store"
        assert not os.path.exists(os.path.join(_audio_env, "meet-off"))

    def test_invitation_true_writes(self, client, _audio_env):
        from infra import bot_invitations, identity, workspaces
        u = identity.upsert_user_by_supabase("sb-g2", "g2@x.com", "G")
        ws = workspaces.create_workspace("P", u["id"])
        bot_invitations.create_invitation(
            user_id=u["id"], workspace_id=ws["id"], platform="google_meet",
            native_meeting_id="meet-on", store_audio=True,
        )
        _post_chunk(client, "meet-on", _wav_bytes(0.1))
        assert os.path.isfile(os.path.join(_audio_env, "meet-on", "000000.wav"))


# --------------------------------------------------------------------------- #
# 4. Decrypt-on-read (_assemble_audio mixes encrypted + legacy plaintext)
# --------------------------------------------------------------------------- #
class TestDecryptOnRead:
    def test_assemble_mixes_encrypted_and_legacy(self, _audio_env):
        from connectors.capture.identify import _assemble_audio
        from infra import audio_crypto as ac

        d = os.path.join(_audio_env, "mix")
        os.makedirs(d)
        enc_pt, legacy_pt = b"AAAA-encrypted", b"BBBB-legacy"
        with open(os.path.join(d, "000000.wav"), "wb") as f:
            f.write(ac.encrypt(enc_pt))
        with open(os.path.join(d, "000001.wav"), "wb") as f:
            f.write(legacy_pt)  # legacy plaintext, no MAGIC
        # a sha256 sidecar must be ignored by assembly
        with open(os.path.join(d, "000000.wav.sha256"), "w") as f:
            f.write("deadbeef")

        assert _assemble_audio("mix") == enc_pt + legacy_pt


# --------------------------------------------------------------------------- #
# 5 + 3. Serving endpoint: full playback, slice range, permission, legacy
# --------------------------------------------------------------------------- #
class TestServingEndpoint:
    def test_owner_full_playback_round_trip(self, client, _audio_env):
        _make_owned_session(client, "owner@x.com", "sid-play")
        pt = _wav_bytes(1.0)
        _post_chunk(client, "sid-play", pt)

        r = client.get("/transcripts/sessions/sid-play/audio")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"].startswith("audio/wav")
        assert r.content == pt  # decrypt-on-read reconstructs the exact plaintext

    def test_segment_slice_returns_correct_range(self, client, _audio_env):
        _make_owned_session(client, "owner2@x.com", "sid-slice")
        _post_chunk(client, "sid-slice", _wav_bytes(1.0))  # 16000 frames

        r = client.get("/transcripts/sessions/sid-slice/audio?start=0.25&end=0.5")
        assert r.status_code == 200
        with wave.open(io.BytesIO(r.content), "rb") as w:
            assert w.getnframes() == 4000  # (0.5-0.25)s * 16000

    def test_legacy_plaintext_still_plays(self, client, _audio_env):
        _make_owned_session(client, "owner3@x.com", "sid-legacy")
        pt = _wav_bytes(0.3)
        d = os.path.join(_audio_env, "sid-legacy")
        os.makedirs(d)
        with open(os.path.join(d, "000000.wav"), "wb") as f:
            f.write(pt)  # legacy plaintext (no encryption)
        r = client.get("/transcripts/sessions/sid-legacy/audio")
        assert r.status_code == 200
        assert r.content == pt

    def test_anonymous_denied(self, client, _audio_env):
        _make_owned_session(client, "owner4@x.com", "sid-anon")
        _post_chunk(client, "sid-anon", _wav_bytes(0.1))
        anon = TestClient(__import__("main").app)  # no auth cookie
        r = anon.get("/transcripts/sessions/sid-anon/audio")
        assert r.status_code == 401

    def test_non_member_denied(self, client, _audio_env, monkeypatch):
        _make_owned_session(client, "owner5@x.com", "sid-priv")
        _post_chunk(client, "sid-priv", _wav_bytes(0.1))
        # A different authenticated user who is NOT a member of the workspace.
        other = TestClient(__import__("main").app)
        from infra import supabase_auth as sb
        monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
        monkeypatch.setattr(sb, "verify_otp", lambda e, t: f"sb-{e}")
        import auth.routes as ar
        monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
        monkeypatch.setattr(ar, "_supabase_verify_otp", lambda e, t: f"sb-{e}")
        _login(other, "intruder@x.com")
        r = other.get("/transcripts/sessions/sid-priv/audio")
        assert r.status_code == 403

    def test_no_audio_404(self, client, _audio_env):
        _make_owned_session(client, "owner6@x.com", "sid-noaudio")
        r = client.get("/transcripts/sessions/sid-noaudio/audio")
        assert r.status_code == 404


# --------------------------------------------------------------------------- #
# 6. Delete audio (owner-gated)
# --------------------------------------------------------------------------- #
class TestDeleteAudio:
    def test_owner_delete_removes_files_and_flips_flag(self, client, _audio_env):
        _make_owned_session(client, "owner7@x.com", "sid-del")
        _post_chunk(client, "sid-del", _wav_bytes(0.2))
        assert os.path.isdir(os.path.join(_audio_env, "sid-del"))

        r = client.delete("/transcripts/sessions/sid-del/audio")
        assert r.status_code == 200, r.text
        assert r.json()["deleted"] is True
        assert not os.path.exists(os.path.join(_audio_env, "sid-del"))
        # read-side flag flipped → player hides; subsequent fetch 404s
        assert client.get("/transcripts/sessions/sid-del/audio").status_code == 404

    def test_non_owner_cannot_delete(self, client, _audio_env, monkeypatch):
        _make_owned_session(client, "owner8@x.com", "sid-del2")
        _post_chunk(client, "sid-del2", _wav_bytes(0.1))
        other = TestClient(__import__("main").app)
        from infra import supabase_auth as sb
        monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
        monkeypatch.setattr(sb, "verify_otp", lambda e, t: f"sb-{e}")
        import auth.routes as ar
        monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
        monkeypatch.setattr(ar, "_supabase_verify_otp", lambda e, t: f"sb-{e}")
        _login(other, "intruder2@x.com")
        r = other.delete("/transcripts/sessions/sid-del2/audio")
        assert r.status_code == 403
        # audio is untouched
        assert os.path.isdir(os.path.join(_audio_env, "sid-del2"))


# --------------------------------------------------------------------------- #
# 7. Invite-time store_audio resolution (gMeet + workspace default)
# --------------------------------------------------------------------------- #
class TestInviteResolution:
    def test_default_keeps_audio(self, client):
        from infra import bot_invitations
        me = _login(client, "host@x.com")
        r = client.post("/api/meetings/invite-bot",
                        json={"meet_url_or_code": "abc-defg-hij",
                              "workspace_id": me["workspace"]["id"]})
        # launch_bot isn't monkeypatched here → may 502, but the invitation row
        # is created BEFORE launch, so the store_audio decision is persisted.
        inv = bot_invitations.find_latest_by_native("abc-defg-hij")
        assert inv is not None
        assert inv["store_audio"] is True  # workspace default = keep

    def test_explicit_false_overrides_default(self, client):
        from infra import bot_invitations, workspaces
        me = _login(client, "host2@x.com")
        # even with a workspace default of True, an explicit False wins
        workspaces.set_audio_store_default(me["workspace"]["id"], True)
        client.post("/api/meetings/invite-bot",
                    json={"meet_url_or_code": "zzz-yyyy-xxx",
                          "workspace_id": me["workspace"]["id"],
                          "store_audio": False})
        inv = bot_invitations.find_latest_by_native("zzz-yyyy-xxx")
        assert inv is not None
        assert inv["store_audio"] is False

    def test_workspace_default_off_propagates(self, client):
        from infra import bot_invitations, workspaces
        me = _login(client, "host3@x.com")
        workspaces.set_audio_store_default(me["workspace"]["id"], False)
        client.post("/api/meetings/invite-bot",
                    json={"meet_url_or_code": "ddd-eeee-fff",
                          "workspace_id": me["workspace"]["id"]})
        inv = bot_invitations.find_latest_by_native("ddd-eeee-fff")
        assert inv is not None
        assert inv["store_audio"] is False
