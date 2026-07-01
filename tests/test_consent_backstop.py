"""P4 Phase 2 (Conclave) — read-time consent backstop in the transcript read path.

On transcript load, names are refreshed from FPM's live consent decision (cached, fail-open):
a confirm that happened without a re-tag surfaces on next load, and revoked consent withholds
the name at read time. FPM is stubbed here.
"""
import pytest
from fastapi.testclient import TestClient

from infra import identity
from transcripts import store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata, Signal


@pytest.fixture(autouse=True)
def _clean_tables():
    from storage.sqlite import _get_conn
    from tests.conftest import reset_workspace_domain_tables
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
    from main import app
    return TestClient(app)


def _login(client, email="alice@example.com"):
    assert client.post("/auth/v1/verify-otp", json={"email": email, "token": "0"}).status_code == 200
    return identity.upsert_user_by_supabase(f"sb-{email}", email)


def _wsid(client):
    return client.get("/api/workspaces").json()["workspaces"][0]["id"]


def _make_session(sid, wsid, owner_id, resolved):
    raw = [RawSegment(speaker=lbl, text=f"{lbl}: hi", start=0.0) for lbl in resolved]
    sess = Session(
        session_id=sid, raw_diarization=raw,
        metadata=SessionMetadata(date="2026-06-14", source="record", resolved_speakers=resolved),
        derived=Derived(summary="d"),
    )
    store.save_session(sess)
    store.set_workspace(sid, workspace_id=wsid, owner_user_id=owner_id, visibility="owner-only")


def _stub_resolve(monkeypatch, mapping):
    import infra.fpm_consent as fc
    monkeypatch.setattr(fc, "consent_resolve_batch_sync", lambda ws, vids: mapping)


def test_confirm_surfaces_on_next_load(client, monkeypatch):
    user = _login(client)
    wsid = _wsid(client)
    # Conclave still has name=None (no re-tag), but FPM now says the binding is confirmed.
    _make_session("bs1", wsid, user["id"],
                  {"Speaker 2": {"voiceprint_id": "vp_b", "name": None, "confidence": 0.9}})
    # confirmed binding = claimed owner + identify-allowed ⇒ consented ⇒ auto-apply (Task #3)
    _stub_resolve(monkeypatch, {"vp_b": {"name": "Alice", "owner_email": "a@x.com",
                                         "visibility": "named", "consented": True}})
    r = client.get("/transcripts/sessions/bs1/transcript")
    assert r.status_code == 200
    seg = r.json()["segments"][0]
    assert seg["speaker"] == "Speaker 2" and seg["speaker_name"] == "Alice"
    # the backstop also persisted the refreshed name
    assert store.load_session("bs1").metadata.resolved_speakers["Speaker 2"]["name"] == "Alice"


def test_revoked_consent_withholds_name_at_read(client, monkeypatch):
    user = _login(client)
    wsid = _wsid(client)
    _make_session("bs2", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_r", "name": "Alice", "confidence": 0.9}})
    _stub_resolve(monkeypatch, {"vp_r": {"name": None, "owner_email": "a@x.com", "visibility": "anonymous"}})
    r = client.get("/transcripts/sessions/bs2/transcript")
    assert r.json()["segments"][0]["speaker_name"] is None  # revoked consent → withheld at read


def test_backstop_fail_open_keeps_stored_name(client, monkeypatch):
    user = _login(client)
    wsid = _wsid(client)
    _make_session("bs3", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_f", "name": "Keep", "confidence": 0.9}})
    import infra.fpm_consent as fc

    def boom(ws, vids):
        raise RuntimeError("fpm unreachable")

    monkeypatch.setattr(fc, "consent_resolve_batch_sync", boom)
    r = client.get("/transcripts/sessions/bs3/transcript")
    assert r.status_code == 200 and r.json()["segments"][0]["speaker_name"] == "Keep"
