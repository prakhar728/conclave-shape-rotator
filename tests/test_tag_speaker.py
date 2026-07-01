"""P4 (Conclave) — POST /api/workspaces/{ws}/meetings/{id}/tag-speaker.

Covers the route contract: auth, label→voiceprint_id mapping, FPM propose (stubbed),
and the confirmed→reresolve flow flipping the name across transcripts. FPM is stubbed,
so this exercises Conclave's half of the seam; the real two-process bind is the
Phase-1 gate (scripts/p4_phase1_gate.py).
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
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return identity.upsert_user_by_supabase(f"sb-{email}", email)


def _wsid(client):
    return client.get("/api/workspaces").json()["workspaces"][0]["id"]


def _make_session(sid, wsid, owner_id, resolved, said_by=None):
    raw = [RawSegment(speaker=lbl, text=f"{lbl}: hi", start=0.0) for lbl in resolved]
    derived = (Derived(summary="s", signals=[Signal(kind="action_item", text="t", said_by=said_by)])
               if said_by else Derived())
    sess = Session(
        session_id=sid, raw_diarization=raw,
        metadata=SessionMetadata(date="2026-06-14", source="record", resolved_speakers=resolved),
        derived=derived,
    )
    store.save_session(sess)
    store.set_workspace(sid, workspace_id=wsid, owner_user_id=owner_id, visibility="owner-only")


def _stub_propose(monkeypatch, result):
    import infra.fpm_consent as fc

    async def fake(*a, **k):
        return result

    monkeypatch.setattr(fc, "propose_binding", fake)


def test_confirmed_tag_reresolves_name_across_meetings(client, monkeypatch):
    user = _login(client)
    wsid = _wsid(client)
    _make_session("m1", wsid, user["id"],
                  {"Speaker 2": {"voiceprint_id": "vp_self", "name": None, "confidence": 0.9}},
                  said_by=["Speaker 2"])
    _make_session("m2", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_self", "name": None, "confidence": 0.8}})
    _stub_propose(monkeypatch, {"proposal_id": "prop_1", "status": "confirmed",
                                "auto_confirmed": True, "voiceprint_id": "vp_self",
                                "name": "Alice", "owner_email": "alice@example.com"})

    r = client.post(f"/api/workspaces/{wsid}/meetings/m1/tag-speaker",
                    json={"label": "Speaker 2", "name": "Alice", "email": "alice@example.com"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["voiceprint_id"] == "vp_self" and body["status"] == "confirmed"

    from api.transcripts_routes import to_transcript
    seg1 = to_transcript(store.load_session("m1"))["segments"][0]
    assert seg1["speaker"] == "Speaker 2"        # immutable label key — never rewritten (C3)
    assert seg1["speaker_name"] == "Alice"       # name projected after re-resolve
    seg2 = to_transcript(store.load_session("m2"))["segments"][0]
    assert seg2["speaker_name"] == "Alice"       # cross-transcript: same voiceprint, both flip
    # C3: said_by stays the label, not the name
    assert store.load_session("m1").derived.signals[0].said_by == ["Speaker 2"]


def test_pending_tag_does_not_flip_name(client, monkeypatch):
    user = _login(client)
    wsid = _wsid(client)
    _make_session("mp", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_p", "name": None, "confidence": 0.5}})
    _stub_propose(monkeypatch, {"proposal_id": "prop_2", "status": "pending",
                                "auto_confirmed": False, "voiceprint_id": "vp_p",
                                "name": None, "owner_email": None})

    r = client.post(f"/api/workspaces/{wsid}/meetings/mp/tag-speaker",
                    json={"label": "Speaker 1", "name": "Bob", "email": "bob@example.com"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    assert store.load_session("mp").metadata.resolved_speakers["Speaker 1"]["name"] is None


def test_unknown_label_404(client, monkeypatch):
    user = _login(client)
    wsid = _wsid(client)
    _make_session("mu", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_u", "name": None, "confidence": 0.5}})
    _stub_propose(monkeypatch, {"status": "confirmed"})  # must not be reached
    r = client.post(f"/api/workspaces/{wsid}/meetings/mu/tag-speaker",
                    json={"label": "Speaker 9", "name": "X", "email": "x@x.com"})
    assert r.status_code == 404


def test_unknown_session_404(client):
    _login(client)
    wsid = _wsid(client)
    r = client.post(f"/api/workspaces/{wsid}/meetings/nope/tag-speaker",
                    json={"label": "Speaker 1", "name": "X", "email": "x@x.com"})
    assert r.status_code == 404


def test_unauthenticated_401(client):
    r = client.post("/api/workspaces/w/meetings/m/tag-speaker",
                    json={"label": "Speaker 1", "name": "X", "email": "x@x.com"})
    assert r.status_code == 401


@pytest.fixture
def email_spy(monkeypatch):
    """Spy on the magic-link send (Resend is in stub mode; we observe calls)."""
    calls: list[dict] = []
    import infra.email as email_mod

    def _spy(**kwargs):
        calls.append(kwargs)
        return {"stub": True, **kwargs}

    monkeypatch.setattr(email_mod, "send_magic_link", _spy)
    return calls


def _share_flags(session_id, email):
    from infra.workspaces import get_meeting_share_scope
    return get_meeting_share_scope(session_id, email)


def test_email_transcript_toggle_shares_and_mails(client, monkeypatch, email_spy):
    """Task #15 — tagging with email_transcript=true grants a transcript+insights
    share, flips the meeting to `shared`, and emails a link-only magic link."""
    user = _login(client)
    wsid = _wsid(client)
    _make_session("mshare", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_x", "name": None, "confidence": 0.6}})
    # Tagging someone else → pending; the share fires regardless of consent status.
    _stub_propose(monkeypatch, {"proposal_id": "p_share", "status": "pending",
                                "auto_confirmed": False, "voiceprint_id": "vp_x",
                                "name": None, "owner_email": None})

    r = client.post(f"/api/workspaces/{wsid}/meetings/mshare/tag-speaker",
                    json={"label": "Speaker 1", "name": "Bob", "email": "bob@example.com",
                          "email_transcript": True})
    assert r.status_code == 200, r.text
    assert r.json()["shared"] is True

    # (1) share row exists at transcript+insights, audio off.
    cfg = _share_flags("mshare", "bob@example.com")
    assert cfg is not None
    assert (cfg.transcript, cfg.insights, cfg.audio) == (True, True, False)

    # (2) meeting flipped to `shared`.
    assert store.get_workspace_fields("mshare")["visibility"] == "shared"

    # (3) a link-only magic link was emailed to the recipient.
    assert [c["recipient_email"] for c in email_spy] == ["bob@example.com"]
    assert "/m/" in email_spy[0]["magic_link_url"]


def test_email_transcript_toggle_off_shares_nothing(client, monkeypatch, email_spy):
    """Regression guard: without the toggle, tagging shares nothing and mails no one."""
    user = _login(client)
    wsid = _wsid(client)
    _make_session("mnoshare", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_y", "name": None, "confidence": 0.6}})
    _stub_propose(monkeypatch, {"proposal_id": "p_noshare", "status": "pending",
                                "auto_confirmed": False, "voiceprint_id": "vp_y",
                                "name": None, "owner_email": None})

    r = client.post(f"/api/workspaces/{wsid}/meetings/mnoshare/tag-speaker",
                    json={"label": "Speaker 1", "name": "Bob", "email": "bob@example.com"})
    assert r.status_code == 200, r.text
    assert r.json()["shared"] is False

    assert _share_flags("mnoshare", "bob@example.com") is None
    assert store.get_workspace_fields("mnoshare")["visibility"] == "owner-only"
    assert email_spy == []


def test_email_transcript_link_resolves_to_meeting(client, monkeypatch, email_spy):
    """The emailed /m/{token} link resolves back to the tagged meeting."""
    user = _login(client)
    wsid = _wsid(client)
    _make_session("mlink", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_z", "name": None, "confidence": 0.6}})
    _stub_propose(monkeypatch, {"proposal_id": "p_link", "status": "pending",
                                "auto_confirmed": False, "voiceprint_id": "vp_z",
                                "name": None, "owner_email": None})

    client.post(f"/api/workspaces/{wsid}/meetings/mlink/tag-speaker",
                json={"label": "Speaker 1", "name": "Bob", "email": "bob@example.com",
                      "email_transcript": True})

    from storage.sqlite import _get_conn
    row = _get_conn().execute(
        "SELECT token FROM magic_links WHERE meeting_session_id = ? AND user_email = ?",
        ("mlink", "bob@example.com"),
    ).fetchone()
    assert row is not None
    resolved = client.get(f"/api/magic-links/{row['token']}")
    assert resolved.status_code == 200
    assert resolved.json()["meeting_session_id"] == "mlink"


def test_session_detail_exposes_workspace_id(client):
    """The meeting view carries workspace_id so the UI knows where to POST tags."""
    user = _login(client)
    wsid = _wsid(client)
    _make_session("ws_detail", wsid, user["id"],
                  {"Speaker 1": {"voiceprint_id": "vp_d", "name": None, "confidence": 0.5}})
    r = client.get("/transcripts/sessions/ws_detail")
    assert r.status_code == 200
    assert r.json()["workspace_id"] == wsid
