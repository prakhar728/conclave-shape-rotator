"""Task #31 — flexible sharing scopes {transcript, insights, audio}.

Two layers of coverage:

1. **Gate unit tests** — `can_see_artifact` and its three wrappers
   (`can_see_transcript` / `can_see_insights` / `can_see_audio`). This is the
   single enforcement seam: a "shared recipient" and a "magic-link viewer" are
   the SAME thing at this layer — both are an authenticated user (the link just
   delivers the sign-in) carrying a `meeting_shares` row keyed by email. Every
   {t,i,a} subset grants/denies exactly the matching artifact; owner + full
   workspace members always pass; the legacy scope enum back-fills to the right
   flags.

2. **HTTP endpoint tests** — the recipient (logged in with the shared email,
   i.e. the magic-link viewer) hits the real routes: the detail view redacts
   insights when insights=off, the transcript endpoint 403s when transcript=off,
   the audio endpoint (Task #30) 403s when audio=off and 200s when audio=on. The
   owner always sees everything, and the old `scope=` API input still works.

3. **Migration backfill test** — runs Alembic 0024 on a FRESH throwaway DB in a
   subprocess (so it never touches the shared per-process test DB) and asserts
   legacy `summary_only`/`summary_and_transcript` rows land on the right flags.
"""
from __future__ import annotations

import itertools
import os
import subprocess
import sys
import textwrap

import pytest
from fastapi.testclient import TestClient

from api.transcripts_routes import (
    can_see_artifact,
    can_see_audio,
    can_see_insights,
    can_see_transcript,
    can_user_see,
)
from infra import identity, workspaces
from infra.workspaces import ShareConfig
from storage import sqlite as _sqlite
from storage.sqlite import _get_conn, _now


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")
    reset_workspace_domain_tables()
    yield


# ---------------------------------------------------------------------------
# Layer 1 — gate unit tests
# ---------------------------------------------------------------------------


@pytest.fixture
def alice() -> dict:
    return identity.upsert_user_by_supabase("sb-alice", "alice@example.com", "A")


@pytest.fixture
def bob() -> dict:
    return identity.upsert_user_by_supabase("sb-bob", "bob@example.com", "B")


@pytest.fixture
def ws(alice: dict) -> dict:
    return workspaces.create_workspace("Personal", alice["id"])


def _row(*, workspace_id, owner_user_id, visibility, session_id="sess-1") -> dict:
    return {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
        "visibility": visibility,
    }


ARTIFACTS = ("transcript", "insights", "audio")
_GATE = {
    "transcript": can_see_transcript,
    "insights": can_see_insights,
    "audio": can_see_audio,
}


def test_owner_sees_all_artifacts(alice, bob, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="owner-only")
    for art in ARTIFACTS:
        assert _GATE[art](alice, row) is True
        assert _GATE[art](bob, row) is False
        assert _GATE[art](None, row) is False


def test_workspace_member_sees_all_artifacts(alice, bob, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="workspace")
    for art in ARTIFACTS:
        assert _GATE[art](bob, row) is False  # not a member yet
    _get_conn().execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role, added_at, added_by) "
        "VALUES (?, ?, 'member', ?, ?)",
        (ws["id"], bob["id"], _now(), alice["id"]),
    )
    for art in ARTIFACTS:
        assert _GATE[art](bob, row) is True


def test_non_shared_and_anonymous_denied_all(alice, bob, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    for art in ARTIFACTS:
        assert _GATE[art](bob, row) is False  # no share row at all
        assert _GATE[art](None, row) is False


@pytest.mark.parametrize("t,i,a", list(itertools.product([False, True], repeat=3)))
def test_every_subset_grants_exactly_its_artifacts(alice, bob, ws, t, i, a):
    """The crux: each {t,i,a} combination gates each endpoint independently."""
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    workspaces.add_meeting_share(
        row["session_id"], bob["email"], alice["id"],
        ShareConfig(transcript=t, insights=i, audio=a),
    )
    # Any non-empty share still lets bob see the SESSION (can_user_see); the
    # per-artifact gates decide WHAT within it.
    assert can_user_see(bob, row) is True
    assert can_see_transcript(bob, row) is t
    assert can_see_insights(bob, row) is i
    assert can_see_audio(bob, row) is a


def test_can_see_artifact_rejects_unknown_artifact(alice, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    with pytest.raises(ValueError):
        can_see_artifact(alice, row, "everything")


# --- Back-compat / backfill semantics --------------------------------------


def test_legacy_summary_only_backfills_to_insights_only(alice, bob, ws):
    """A 'summary_only'-era share behaves identically after backfill:
    insights YES, transcript NO, audio NO."""
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    workspaces.add_meeting_share(
        row["session_id"], bob["email"], alice["id"], scope="summary_only"
    )
    assert can_see_insights(bob, row) is True
    assert can_see_transcript(bob, row) is False
    assert can_see_audio(bob, row) is False


def test_legacy_summary_and_transcript_maps_to_t1_i1_a0(alice, bob, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    workspaces.add_meeting_share(
        row["session_id"], bob["email"], alice["id"], scope="summary_and_transcript"
    )
    assert can_see_transcript(bob, row) is True
    assert can_see_insights(bob, row) is True
    assert can_see_audio(bob, row) is False


def test_default_share_grants_transcript_and_insights_not_audio(alice, bob, ws):
    """No config + no scope → pre-#31 default (summary + transcript, no audio)."""
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    workspaces.add_meeting_share(row["session_id"], bob["email"], alice["id"])
    assert can_see_transcript(bob, row) is True
    assert can_see_insights(bob, row) is True
    assert can_see_audio(bob, row) is False


def test_shareconfig_legacy_mapping_helpers():
    assert ShareConfig.from_legacy_scope("summary_only") == ShareConfig(False, True, False)
    assert ShareConfig.from_legacy_scope("summary_and_transcript") == ShareConfig(True, True, False)
    assert ShareConfig.default() == ShareConfig(True, True, False)
    assert ShareConfig(True, True, False).to_legacy_scope() == "summary_and_transcript"
    assert ShareConfig(False, True, False).to_legacy_scope() == "summary_only"
    with pytest.raises(ValueError):
        ShareConfig.from_legacy_scope("nonsense")


def test_list_meeting_shares_exposes_flags_and_legacy_scope(alice, bob, ws):
    workspaces.add_meeting_share(
        "sess-9", bob["email"], alice["id"], ShareConfig(True, False, True)
    )
    shares = workspaces.list_meeting_shares("sess-9")
    assert len(shares) == 1
    s = shares[0]
    assert s["share_transcript"] is True
    assert s["share_insights"] is False
    assert s["share_audio"] is True
    assert s["scope"] == "summary_and_transcript"  # derived from transcript flag


# ---------------------------------------------------------------------------
# Layer 2 — HTTP endpoint tests (recipient == magic-link viewer)
# ---------------------------------------------------------------------------


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


def _login(client: TestClient, email: str) -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200
    return r.json()


def _seed_shared_meeting(*, owner_email: str, session_id: str = "sess-http") -> dict:
    owner = identity.upsert_user_by_supabase(f"sb-{owner_email}", owner_email)
    wsp = workspaces.create_workspace("Personal", owner["id"])
    _sqlite.save_transcript_session(
        session_id=session_id,
        source="recato",
        session_date="2026-06-01",
        raw_diarization=[{"speaker": "S1", "text": "hello world"}],
        metadata={"date": "2026-06-01", "source": "recato"},
        derived={
            "summary": "the secret summary",
            "signals": [{"kind": "action_item", "text": "do the thing"}],
            "entities": [{"name": "Acme", "type": "org"}],
        },
    )
    _sqlite.set_transcript_workspace(
        session_id=session_id,
        workspace_id=wsp["id"],
        owner_user_id=owner["id"],
        visibility="shared",
    )
    return {"owner": owner, "workspace": wsp, "session_id": session_id}


def _add_share(client, session_id, email, **flags):
    r = client.post(f"/api/meetings/{session_id}/shares", json={"email": email, **flags})
    assert r.status_code == 201, r.text
    return r


def test_owner_detail_view_has_all_and_flags_true(client):
    seed = _seed_shared_meeting(owner_email="own1@example.com")
    _login(client, "own1@example.com")
    v = client.get(f"/transcripts/sessions/{seed['session_id']}").json()
    assert v["summary"] == "the secret summary"
    assert v["can_view_insights"] is True
    assert v["can_view_transcript"] is True
    assert v["can_view_audio"] is True


def test_recipient_insights_off_redacts_summary_signals_entities(client):
    seed = _seed_shared_meeting(owner_email="own2@example.com")
    _login(client, "own2@example.com")
    _add_share(client, seed["session_id"], "viewer@example.com",
               transcript=True, insights=False, audio=False)

    # viewer signs in via their magic-link email → authenticated as that email.
    _login(client, "viewer@example.com")
    v = client.get(f"/transcripts/sessions/{seed['session_id']}").json()
    assert v["can_view_insights"] is False
    assert v["summary"] is None
    assert v["signals"] == []
    assert v["entities"] == []
    assert v["signal_count"] == 0
    assert v["entity_count"] == 0
    # transcript flag still surfaced independently
    assert v["can_view_transcript"] is True


def test_recipient_insights_on_sees_summary(client):
    seed = _seed_shared_meeting(owner_email="own3@example.com")
    _login(client, "own3@example.com")
    _add_share(client, seed["session_id"], "viewer3@example.com",
               transcript=False, insights=True, audio=False)
    _login(client, "viewer3@example.com")
    v = client.get(f"/transcripts/sessions/{seed['session_id']}").json()
    assert v["can_view_insights"] is True
    assert v["summary"] == "the secret summary"
    assert len(v["signals"]) == 1
    assert v["can_view_transcript"] is False


def test_recipient_transcript_gate(client):
    seed = _seed_shared_meeting(owner_email="own4@example.com")
    _login(client, "own4@example.com")
    _add_share(client, seed["session_id"], "vt@example.com",
               transcript=True, insights=False, audio=False)
    _login(client, "vt@example.com")
    assert client.get(f"/transcripts/sessions/{seed['session_id']}/transcript").status_code == 200

    # Flip transcript off (re-share) → now 403.
    _login(client, "own4@example.com")
    _add_share(client, seed["session_id"], "vt@example.com",
               transcript=False, insights=True, audio=False)
    _login(client, "vt@example.com")
    assert client.get(f"/transcripts/sessions/{seed['session_id']}/transcript").status_code == 403


def test_recipient_audio_gate(client, monkeypatch):
    seed = _seed_shared_meeting(owner_email="own5@example.com")
    _login(client, "own5@example.com")

    # audio=off → 403 (gate fires before audio assembly, no stub needed).
    _add_share(client, seed["session_id"], "va@example.com",
               transcript=True, insights=True, audio=False)
    _login(client, "va@example.com")
    assert client.get(f"/transcripts/sessions/{seed['session_id']}/audio").status_code == 403

    # audio=on → 200 (stub the decrypt-assemble to return bytes).
    import connectors.capture.identify as _ident
    monkeypatch.setattr(_ident, "_assemble_audio", lambda sid: b"RIFFfakewav")
    _login(client, "own5@example.com")
    _add_share(client, seed["session_id"], "va@example.com",
               transcript=True, insights=True, audio=True)
    _login(client, "va@example.com")
    r = client.get(f"/transcripts/sessions/{seed['session_id']}/audio")
    assert r.status_code == 200
    assert r.content == b"RIFFfakewav"


def test_old_scope_enum_api_input_still_works(client):
    seed = _seed_shared_meeting(owner_email="own6@example.com")
    _login(client, "own6@example.com")
    # Legacy client sends only `scope`.
    r = client.post(
        f"/api/meetings/{seed['session_id']}/shares",
        json={"email": "legacy@example.com", "scope": "summary_only"},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["insights"] is True
    assert body["transcript"] is False
    assert body["audio"] is False
    assert body["scope"] == "summary_only"

    # And it enforces: legacy summary_only recipient sees insights, not transcript.
    _login(client, "legacy@example.com")
    v = client.get(f"/transcripts/sessions/{seed['session_id']}").json()
    assert v["summary"] == "the secret summary"
    assert v["can_view_transcript"] is False
    assert client.get(f"/transcripts/sessions/{seed['session_id']}/transcript").status_code == 403


def test_list_shares_returns_flags(client):
    seed = _seed_shared_meeting(owner_email="own7@example.com")
    _login(client, "own7@example.com")
    _add_share(client, seed["session_id"], "f@example.com",
               transcript=False, insights=True, audio=True)
    shares = client.get(f"/api/meetings/{seed['session_id']}/shares").json()["shares"]
    row = next(s for s in shares if s["email"] == "f@example.com")
    assert row["transcript"] is False
    assert row["insights"] is True
    assert row["audio"] is True


# ---------------------------------------------------------------------------
# Layer 3 — migration backfill (isolated fresh DB via subprocess)
# ---------------------------------------------------------------------------

# Runs in a child process against a throwaway DB so it never mutates the shared
# per-process test DB (the suite would break if we downgraded/upgraded it live).
# Seeds legacy `scope` rows at 0023, applies 0024, asserts the flags. This is the
# gate that catches a broken backfill UPDATE in the migration (mutation-audit #5).
_MIGRATION_PROOF = textwrap.dedent(
    """
    from storage import sqlite as s
    s._get_conn()  # runs legacy _init_schema on CONCLAVE_DB_PATH
    from alembic.config import Config
    from alembic import command
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "0023_inperson_agenda")
    conn = s._get_conn()
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO meeting_shares (session_id,user_email,granted_by,granted_at,scope) "
        "VALUES ('s1','only@x','o',?, 'summary_only')", (s._now(),))
    conn.execute(
        "INSERT INTO meeting_shares (session_id,user_email,granted_by,granted_at,scope) "
        "VALUES ('s1','full@x','o',?, 'summary_and_transcript')", (s._now(),))
    conn.commit()
    command.upgrade(cfg, "0024_meeting_share_artifact_flags")
    rows = {r["user_email"]: (r["share_transcript"], r["share_insights"], r["share_audio"])
            for r in s._get_conn().execute(
                "SELECT user_email,share_transcript,share_insights,share_audio FROM meeting_shares")}
    cols = [r[1] for r in s._get_conn().execute("PRAGMA table_info(meeting_shares)")]
    assert rows["only@x"] == (0, 1, 0), rows["only@x"]
    assert rows["full@x"] == (1, 1, 0), rows["full@x"]
    assert "scope" not in cols, cols
    # Downgrade round-trip reconstructs the enum from the flags.
    command.downgrade(cfg, "0023_inperson_agenda")
    sc = {r["user_email"]: r["scope"]
          for r in s._get_conn().execute("SELECT user_email,scope FROM meeting_shares")}
    assert sc["only@x"] == "summary_only" and sc["full@x"] == "summary_and_transcript", sc
    print("MIGRATION_BACKFILL_OK")
    """
)


def test_migration_0024_backfills_legacy_scope(tmp_path):
    db = tmp_path / "backfill.db"
    env = dict(os.environ)
    env["CONCLAVE_DB_PATH"] = str(db)
    env["CONCLAVE_DB_URL"] = f"sqlite:///{db}"
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    proc = subprocess.run(
        [sys.executable, "-c", _MIGRATION_PROOF],
        cwd=repo_root,
        env=env,
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    assert "MIGRATION_BACKFILL_OK" in proc.stdout
