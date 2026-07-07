"""Task #32 — Conclave workspace multi-membership.

Covers the whole surface:
  - invite → accept → `workspace_members` row with the right role
  - accept-on-signup (invite issued before the invitee had an account)
  - owner-only manage gate (a member can't invite / list / remove)
  - CONSERVATIVE default (§0b-D): bare membership does NOT expose a meeting
  - share-to-workspace → every member sees it (full artifacts, decision B)
  - share-to-member → only that member sees it (others don't)
  - per-viewer name overlay (decision A): adder-only names resolve per THEIR host,
    not the owner's, and are never persisted (no cross-viewer clobber / leak)
  - host_user = the RECORDER at identify (upgrades #2's owner-placeholder)
  - revoke → access gone
  - single-owner backward-compat intact
  - owner_only confidential lock blocks workspace sharing
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from infra import identity, workspaces
from storage import sqlite as _sqlite


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn = _sqlite._get_conn
    _get_conn().execute("DELETE FROM transcript_sessions")
    for t in ("workspace_invites", "meeting_workspace_shares", "inperson_recorder"):
        try:
            _get_conn().execute(f"DELETE FROM {t}")
        except Exception:  # noqa: BLE001
            pass
    reset_workspace_domain_tables()
    from infra import fpm_consent
    fpm_consent._cache.clear()
    yield


@pytest.fixture
def client(monkeypatch) -> TestClient:
    import auth.routes as ar
    from infra import supabase_auth as sb
    monkeypatch.setattr(sb, "supabase_enabled", lambda: True)
    monkeypatch.setattr(sb, "send_otp", lambda email: None)
    monkeypatch.setattr(sb, "verify_otp", lambda email, token: f"sb-{email}")
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    # Never hit a real email backend on invite.
    from infra import email as _email
    monkeypatch.setattr(_email, "send_workspace_invite", lambda **kw: {"stub": True})
    from main import app
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "0"})
    assert r.status_code == 200, r.text
    return r.json()


def _shared_ws(client: TestClient, email: str) -> str:
    """Log in `email` and create a fresh (non-Personal) workspace they own."""
    _login(client, email)
    r = client.post("/api/workspaces", json={"name": "Team"})
    assert r.status_code == 201, r.text
    return r.json()["workspace"]["id"]


# ---------------------------------------------------------------------------
# Invite → accept → member
# ---------------------------------------------------------------------------


def test_invite_then_accept_creates_member_with_role(client):
    # Bob already has an account (signs in on his OWN client → no auto-accept race).
    from main import app
    bob_client = TestClient(app)
    bob = _login(bob_client, "bob@x.com")

    ws_id = _shared_ws(client, "owner@x.com")
    r = client.post(f"/api/workspaces/{ws_id}/members",
                    json={"email": "bob@x.com", "role": "member"})
    assert r.status_code == 201
    # The token isn't returned by the HTTP route (it's emailed) — read it from the store.
    token = _sqlite._get_conn().execute(
        "SELECT token FROM workspace_invites WHERE workspace_id = ?", (ws_id,)
    ).fetchone()["token"]

    # Bob (already signed in on his client) accepts via the token.
    acc = bob_client.post("/api/workspaces/accept-invite", json={"token": token})
    assert acc.status_code == 200, acc.text
    assert acc.json()["role"] == "member"
    assert workspaces.get_member_role(ws_id, bob["user"]["id"]) == "member"
    assert workspaces.list_pending_invites(ws_id) == []  # consumed


def test_accept_on_signup_hydrates_pending_invite(client):
    ws_id = _shared_ws(client, "owner2@x.com")
    client.post(f"/api/workspaces/{ws_id}/members", json={"email": "late@x.com"})
    # `late@x.com` has no account yet. First sign-in should auto-accept the invite.
    late = _login(client, "late@x.com")
    assert workspaces.is_member(ws_id, late["user"]["id"]) is True


def test_accept_unknown_token_404s(client):
    _login(client, "nobody@x.com")
    r = client.post("/api/workspaces/accept-invite", json={"token": "bogus"})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Owner-only manage gate (§0b-C)
# ---------------------------------------------------------------------------


def _seed_owner_and_member(client) -> tuple[str, dict, dict]:
    ws_id = _shared_ws(client, "owner3@x.com")
    owner = identity.get_user_by_email("owner3@x.com")
    client.post(f"/api/workspaces/{ws_id}/members", json={"email": "member3@x.com"})
    member = _login(client, "member3@x.com")["user"]  # auto-accepted on signup
    return ws_id, owner, member


def test_member_cannot_invite_list_or_remove(client):
    ws_id, owner, member = _seed_owner_and_member(client)
    # Member is signed in (from _seed). All manage endpoints are 403 for them.
    assert client.post(f"/api/workspaces/{ws_id}/members",
                       json={"email": "x@x.com"}).status_code == 403
    assert client.get(f"/api/workspaces/{ws_id}/members").status_code == 403
    assert client.delete(
        f"/api/workspaces/{ws_id}/members/{owner['id']}").status_code == 403


def test_owner_lists_members_and_removes(client):
    ws_id, owner, member = _seed_owner_and_member(client)
    _login(client, "owner3@x.com")
    listing = client.get(f"/api/workspaces/{ws_id}/members").json()
    emails = {m["email"] for m in listing["members"]}
    assert emails == {"owner3@x.com", "member3@x.com"}
    # Remove the member → access gone.
    r = client.delete(f"/api/workspaces/{ws_id}/members/{member['id']}")
    assert r.status_code == 200
    assert workspaces.is_member(ws_id, member["id"]) is False


def test_cannot_remove_last_owner(client):
    ws_id = _shared_ws(client, "solo@x.com")
    owner = identity.get_user_by_email("solo@x.com")
    r = client.delete(f"/api/workspaces/{ws_id}/members/{owner['id']}")
    assert r.status_code == 409


def test_invite_already_member_409(client):
    ws_id, owner, member = _seed_owner_and_member(client)
    _login(client, "owner3@x.com")
    r = client.post(f"/api/workspaces/{ws_id}/members", json={"email": "member3@x.com"})
    assert r.status_code == 409


# ---------------------------------------------------------------------------
# Meeting visibility — conservative default + explicit shares
# ---------------------------------------------------------------------------


def _seed_meeting(ws_id: str, owner_id: str, session_id: str, *,
                  resolved=None, recorder=None, visibility="owner-only") -> None:
    _sqlite.save_transcript_session(
        session_id=session_id, source="record", session_date="2026-07-01",
        raw_diarization=[{"speaker": "S1", "text": "hi"}],
        metadata={"date": "2026-07-01", "source": "record",
                  "resolved_speakers": resolved or {}},
        derived={"summary": "secret", "signals": [], "entities": []},
    )
    _sqlite.set_transcript_workspace(session_id=session_id, workspace_id=ws_id,
                                     owner_user_id=owner_id, visibility=visibility)
    if recorder:
        _sqlite.set_transcript_recorder(session_id, recorder)


def test_member_does_not_see_unshared_meeting(client):
    ws_id, owner, member = _seed_owner_and_member(client)
    _seed_meeting(ws_id, owner["id"], "m-priv")
    # Owner sees it; member does not (owner-private default, §0b-D).
    _login(client, "owner3@x.com")
    assert client.get("/transcripts/sessions/m-priv").status_code == 200
    _login(client, "member3@x.com")
    assert client.get("/transcripts/sessions/m-priv").status_code == 403
    # And it isn't in the member's workspace meetings list.
    listing = client.get(f"/api/workspaces/{ws_id}/meetings").json()["meetings"]
    assert all(m["session_id"] != "m-priv" for m in listing)


def test_share_to_workspace_grants_all_members_full(client):
    ws_id, owner, member = _seed_owner_and_member(client)
    _seed_meeting(ws_id, owner["id"], "m-ws")
    _login(client, "owner3@x.com")
    r = client.post("/api/meetings/m-ws/share-workspace", json={"share": True})
    assert r.status_code == 201 and r.json()["shared_to_workspace"] is True
    # Member now sees the session AND full artifacts (decision B).
    _login(client, "member3@x.com")
    v = client.get("/transcripts/sessions/m-ws").json()
    assert v["summary"] == "secret"
    assert v["can_view_transcript"] and v["can_view_insights"] and v["can_view_audio"]
    assert any(m["session_id"] == "m-ws"
               for m in client.get(f"/api/workspaces/{ws_id}/meetings").json()["meetings"])
    # Un-share → gone again.
    _login(client, "owner3@x.com")
    client.post("/api/meetings/m-ws/share-workspace", json={"share": False})
    _login(client, "member3@x.com")
    assert client.get("/transcripts/sessions/m-ws").status_code == 403


def test_share_to_specific_member_only(client):
    ws_id, owner, member = _seed_owner_and_member(client)
    # Add a SECOND member who should NOT see the member-specific share.
    _login(client, "owner3@x.com")
    client.post(f"/api/workspaces/{ws_id}/members", json={"email": "other@x.com"})
    other = _login(client, "other@x.com")["user"]
    _seed_meeting(ws_id, owner["id"], "m-mem")
    _login(client, "owner3@x.com")
    r = client.post("/api/meetings/m-mem/share-member", json={"email": "member3@x.com"})
    assert r.status_code == 201
    _login(client, "member3@x.com")
    v = client.get("/transcripts/sessions/m-mem")
    assert v.status_code == 200 and v.json()["can_view_audio"] is True  # full (decision B)
    _login(client, "other@x.com")
    assert client.get("/transcripts/sessions/m-mem").status_code == 403


def test_member_share_grants_full_even_with_restricted_config(client):
    """Decision B: a workspace MEMBER granted via a per-recipient share sees FULL
    artifacts even if the share's config withholds some (a plain restricted share on
    a NON-member would gate per-artifact — this pins the member-full branch)."""
    ws_id, owner, member = _seed_owner_and_member(client)
    _seed_meeting(ws_id, owner["id"], "m-restrict")
    # Owner shares to the member via the general /shares endpoint with audio OFF.
    _login(client, "owner3@x.com")
    r = client.post("/api/meetings/m-restrict/shares",
                    json={"email": "member3@x.com",
                          "transcript": True, "insights": True, "audio": False})
    assert r.status_code == 201
    # The member still sees audio — because they're a member (decision B), not the flags.
    _login(client, "member3@x.com")
    v = client.get("/transcripts/sessions/m-restrict").json()
    assert v["can_view_audio"] is True


def test_inperson_webhook_defaults_owner_private(client, monkeypatch):
    """The in-person finalize webhook binds a walk-up meeting as OWNER-PRIVATE (§0b-D):
    a bare workspace member does NOT auto-see it (guards the webhook-level default)."""
    monkeypatch.delenv("CAPTURE_WEBHOOK_SECRET", raising=False)
    ws_id, owner, member = _seed_owner_and_member(client)
    native = "inperson-wh-1"
    # Seed the live buffer so finalize materializes an "accepted" session (in-person has
    # no bot_invitation → the webhook binds via the payload workspace_id).
    _sqlite.append_live_segment(native, 0,
                                {"start": 0.0, "end": 1.0, "text": "hello", "speaker": "S1"})
    body = {
        "event_id": "evt_wh_1", "event_type": "meeting.completed", "api_version": "v1",
        "created_at": "2026-07-01T10:00:00Z",
        "data": {"meeting": {"id": 1, "platform": "in_person",
                             "native_meeting_id": native, "status": "completed",
                             "workspace_id": ws_id}},
    }
    r = client.post("/api/webhooks/capture/meeting-completed", json=body)
    assert r.status_code == 202 and r.json()["status"] == "accepted", r.text
    # Owner sees it; the bare member does NOT (owner-private default).
    _login(client, "owner3@x.com")
    assert client.get(f"/transcripts/sessions/{native}").status_code == 200
    _login(client, "member3@x.com")
    assert client.get(f"/transcripts/sessions/{native}").status_code == 403


def test_inperson_webhook_makes_recorder_the_owner(client, monkeypatch):
    """#ownership: the RECORDER owns their walk-up meeting, not the workspace creator — so the person
    who recorded gets share/editor/retention/delete on their own recording even in someone else's ws."""
    monkeypatch.delenv("CAPTURE_WEBHOOK_SECRET", raising=False)
    ws_id, owner, member = _seed_owner_and_member(client)
    native = "inperson-rec-owner-1"
    from infra import inperson_recorder
    inperson_recorder.set_recorder(native, member["id"], workspace_id=ws_id)  # the MEMBER recorded it
    _sqlite.append_live_segment(native, 0,
                                {"start": 0.0, "end": 1.0, "text": "hi", "speaker": "S1"})
    body = {
        "event_id": "evt_rec_owner", "event_type": "meeting.completed", "api_version": "v1",
        "created_at": "2026-07-01T10:00:00Z",
        "data": {"meeting": {"id": 2, "platform": "in_person",
                             "native_meeting_id": native, "status": "completed",
                             "workspace_id": ws_id}},
    }
    r = client.post("/api/webhooks/capture/meeting-completed", json=body)
    assert r.status_code == 202 and r.json()["status"] == "accepted", r.text
    # The recorder (member) now OWNS it — sees it + is_owner — despite not being the workspace creator.
    _login(client, "member3@x.com")
    got = client.get(f"/transcripts/sessions/{native}")
    assert got.status_code == 200, got.text
    assert got.json().get("is_owner") is True


def test_owner_only_lock_blocks_workspace_share(client):
    ws_id, owner, member = _seed_owner_and_member(client)
    _seed_meeting(ws_id, owner["id"], "m-lock")
    _login(client, "owner3@x.com")
    assert client.post("/api/meetings/m-lock/owner-only",
                       json={"locked": True}).status_code == 200
    r = client.post("/api/meetings/m-lock/share-workspace", json={"share": True})
    assert r.status_code == 409
    assert client.post("/api/meetings/m-lock/share-member",
                       json={"email": "member3@x.com"}).status_code == 409


# ---------------------------------------------------------------------------
# Per-viewer name overlay (decision A) + recorder host (§0a / decision A write)
# ---------------------------------------------------------------------------


def _stub_per_host_resolve(monkeypatch, per_host: dict, floor: dict):
    """Stub consent_resolve: return `per_host[host]` for a known host, else `floor`."""
    import infra.fpm_consent as fc

    def _resolve(ws, vids, host_user=None):
        return per_host.get(host_user, floor)

    monkeypatch.setattr(fc, "consent_resolve_batch_sync", _resolve)


def test_per_viewer_overlay_adder_only_not_leaked(client, monkeypatch):
    """An adder-only edge added by the recorder resolves for the recorder's host but is
    withheld from another member viewing the SAME meeting — and never persisted."""
    ws_id, owner, member = _seed_owner_and_member(client)
    resolved = {"S1": {"voiceprint_id": "vp_x", "name": None, "confidence": 0.9}}
    # owner recorded it; share to the whole workspace so the member can open it.
    _seed_meeting(ws_id, owner["id"], "m-ov", resolved=resolved, recorder=owner["id"])
    workspaces.add_meeting_workspace_share("m-ov", ws_id, owner["id"])

    _stub_per_host_resolve(
        monkeypatch,
        per_host={"owner3@x.com": {"vp_x": {"name": "Carol", "consented": True}}},
        floor={"vp_x": {"name": None}},  # scope-wide floor + non-adder host → withheld
    )

    # Owner (the adder) sees "Carol".
    _login(client, "owner3@x.com")
    seg = client.get("/transcripts/sessions/m-ov/transcript").json()["segments"][0]
    assert seg["speaker_name"] == "Carol"
    # The private name is NOT persisted (baseline stays scope-wide/None) → no leak vector.
    assert _sqlite.get_transcript_workspace_fields  # sanity
    from transcripts import store
    assert store.load_session("m-ov").metadata.resolved_speakers["S1"]["name"] is None

    # The other member sees the SAME meeting with the name WITHHELD.
    _login(client, "member3@x.com")
    seg2 = client.get("/transcripts/sessions/m-ov/transcript").json()["segments"][0]
    assert seg2["speaker_name"] is None


def test_meeting_host_email_prefers_recorder(client):
    """identify host = the stamped recorder, falling back to the workspace owner."""
    from infra import fpm_consent
    ws_id, owner, member = _seed_owner_and_member(client)
    # No recorder stamped → falls back to the workspace owner's email.
    _seed_meeting(ws_id, owner["id"], "m-h1")
    assert fpm_consent.meeting_host_email("m-h1", ws_id) == "owner3@x.com"
    # Recorder = the member → host is the member, NOT the owner (the #2 upgrade).
    _seed_meeting(ws_id, owner["id"], "m-h2", recorder=member["id"])
    assert fpm_consent.meeting_host_email("m-h2", ws_id) == "member3@x.com"


@pytest.mark.asyncio
async def test_identify_meeting_uses_recorder_as_host(client, monkeypatch):
    """identify_meeting passes the RECORDER (not the owner) as host_user to VFTE."""
    ws_id, owner, member = _seed_owner_and_member(client)
    _seed_meeting(ws_id, owner["id"], "m-id", recorder=member["id"])

    import connectors.capture.identify as idmod
    from config import settings
    from infra import fpm_consent
    monkeypatch.setattr(settings, "inperson_via_capture", False, raising=False)
    monkeypatch.setattr(idmod, "_assemble_audio", lambda nid: b"RIFFwav")
    captured = {}

    async def _fake_diarize(ws, audio, *, tag="offline", host_user=None, **kw):
        captured["host_user"] = host_user
        return []  # empty → identify_meeting returns without needing reconcile

    monkeypatch.setattr(fpm_consent, "diarize_audio", _fake_diarize)
    await idmod.identify_meeting("m-id", "m-id", ws_id)
    assert captured["host_user"] == "member3@x.com"  # the recorder, not the owner


def test_recorder_stash_endpoint(client):
    ws_id, owner, member = _seed_owner_and_member(client)
    _login(client, "member3@x.com")
    r = client.post(f"/api/workspaces/{ws_id}/record/recorder", json={"uid": "u-1"})
    assert r.status_code == 204
    from infra import inperson_recorder
    assert inperson_recorder.pop_recorder("u-1") == member["id"]
    assert inperson_recorder.pop_recorder("u-1") is None  # consume-once


# ---------------------------------------------------------------------------
# Backward-compat
# ---------------------------------------------------------------------------


def test_single_owner_personal_workspace_still_works(client):
    """A user's auto Personal workspace + their own meeting is unaffected."""
    me = _login(client, "solo2@x.com")
    ws_id = client.get("/api/workspaces").json()["workspaces"][0]["id"]
    _seed_meeting(ws_id, me["user"]["id"], "m-solo")
    assert client.get("/transcripts/sessions/m-solo").status_code == 200
    listing = client.get(f"/api/workspaces/{ws_id}/meetings").json()["meetings"]
    assert any(m["session_id"] == "m-solo" for m in listing)


def test_legacy_workspace_visibility_still_grants_members(client):
    """Pre-#32 in-person meetings stored as visibility='workspace' stay visible to
    members (back-compat for the old default)."""
    ws_id, owner, member = _seed_owner_and_member(client)
    _seed_meeting(ws_id, owner["id"], "m-legacy", visibility="workspace")
    _login(client, "member3@x.com")
    assert client.get("/transcripts/sessions/m-legacy").status_code == 200
