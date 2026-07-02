"""Task #42 — owner delete (hard cascade) + processing/failed lifecycle.

Covers: the `meeting_lifecycle` mapping (incl. the staleness cutoff), the
`delete_session_cascade` primitive (row + FK children + non-FK side tables +
idempotency), the owner-gated DELETE + retry endpoints, and the empty-transcript
fast-fail that stops the eternal "processing" card.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from infra.meeting_lifecycle import STALE_ENRICH_MINUTES, meeting_lifecycle
from transcripts import store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata

NOW = datetime(2026, 7, 2, 15, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


# --- lifecycle helper ------------------------------------------------------

def test_lifecycle_done_when_summary_present():
    assert meeting_lifecycle("pending", True, _iso(NOW), NOW) == "done"


@pytest.mark.parametrize("status", ["ok", "skipped"])
def test_lifecycle_done_on_terminal_ok_statuses(status):
    assert meeting_lifecycle(status, False, _iso(NOW), NOW) == "done"


def test_lifecycle_failed_on_failed_status():
    assert meeting_lifecycle("failed", False, _iso(NOW), NOW) == "failed"


def test_lifecycle_processing_when_pending_and_fresh():
    fresh = _iso(NOW - timedelta(minutes=2))
    assert meeting_lifecycle("pending", False, fresh, NOW) == "processing"


def test_lifecycle_failed_when_pending_past_staleness_cutoff():
    stale = _iso(NOW - timedelta(minutes=STALE_ENRICH_MINUTES + 1))
    assert meeting_lifecycle("pending", False, stale, NOW) == "failed"


def test_lifecycle_processing_when_no_timestamp_legacy_safe():
    # No created_at → can't age it out; stays processing rather than falsely failed.
    assert meeting_lifecycle("pending", False, None, NOW) == "processing"


# --- cascade delete primitive ----------------------------------------------

def _save(sid: str, *, text: str = "hello") -> Session:
    sess = Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="A", text=text, start=0.0)],
        metadata=SessionMetadata(date="2026-07-02", source="capture"),
        derived=Derived(summary="s"),
    )
    store.save_session(sess)
    return sess


def test_delete_cascade_removes_row_side_tables_and_is_idempotent():
    from storage import sqlite as sq

    from infra import identity, workspaces as wsp

    sid = "del-1"
    _save(sid)
    conn = sq._get_conn()
    # Seed both a session_id-keyed side row (meeting_shares) and a
    # native_meeting_id-keyed one (live_segments), plus an FK-cascade child (v2).
    owner = identity.upsert_user_by_supabase("sb-owner-del", "owner-del@x.com")
    wsp.add_meeting_share(sid, "guest@x.com", owner["id"])
    store.append_segment(sid, 0, {"speaker": "A", "text": "x", "start": 0.0})
    store.create_v2_draft(sid)  # FK child with ON DELETE CASCADE
    assert store.load_v2(sid) is not None

    assert store.delete_session(sid) is True
    # Row gone.
    assert store.load_session(sid) is None
    # Non-FK side tables swept (session-keyed + native-keyed).
    assert conn.execute(
        "SELECT COUNT(*) FROM meeting_shares WHERE session_id = ?", (sid,)
    ).fetchone()[0] == 0
    assert conn.execute(
        "SELECT COUNT(*) FROM live_segments WHERE native_meeting_id = ?", (sid,)
    ).fetchone()[0] == 0
    # FK-cascade child gone with the row.
    assert store.load_v2(sid) is None
    # Idempotent: second delete reports "didn't exist".
    assert store.delete_session(sid) is False


# --- endpoints -------------------------------------------------------------

@pytest.fixture(autouse=True)
def _clean():
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


def _login(client: TestClient, email: str) -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return r.json()


def _owned(client: TestClient, email: str, sid: str):
    me = _login(client, email)
    uid, ws_id = me["user"]["id"], me["workspace"]["id"]
    _save(sid)
    store.set_workspace(sid, ws_id, uid, visibility="owner-only")
    return me


def test_owner_can_delete_meeting(client):
    _owned(client, "owner@x.com", "d-ok")
    r = client.delete("/transcripts/sessions/d-ok")
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    assert store.load_session("d-ok") is None


def test_non_owner_cannot_delete(client):
    _owned(client, "owner@x.com", "d-403")
    _login(client, "intruder@x.com")
    r = client.delete("/transcripts/sessions/d-403")
    assert r.status_code == 403
    assert store.load_session("d-403") is not None  # untouched


def test_delete_unknown_session_404(client):
    _login(client, "owner@x.com")
    assert client.delete("/transcripts/sessions/nope").status_code == 404


def test_owner_retry_resets_status_and_enqueues(client, monkeypatch):
    _owned(client, "owner@x.com", "r-1")
    # Mark it failed, then retry.
    s = store.load_session("r-1")
    s.metadata.enrichment_status = "failed"
    store.set_metadata("r-1", s.metadata)
    calls = []
    from connectors.jobs import enqueue
    monkeypatch.setattr(enqueue, "enrich", lambda sid: calls.append(sid))
    r = client.post("/transcripts/sessions/r-1/retry-enrich")
    assert r.status_code == 200, r.text
    assert calls == ["r-1"]
    assert store.load_session("r-1").metadata.enrichment_status == "pending"


def test_non_owner_cannot_retry(client):
    _owned(client, "owner@x.com", "r-403")
    _login(client, "intruder@x.com")
    assert client.post("/transcripts/sessions/r-403/retry-enrich").status_code == 403


# --- empty-transcript fast-fail --------------------------------------------

def test_empty_transcript_fast_fails_without_enrich(monkeypatch):
    from api import transcripts_routes as tr

    sess = Session(
        session_id="empty-1",
        raw_diarization=[RawSegment(speaker="A", text="   ", start=0.0)],  # blank
        metadata=SessionMetadata(date="2026-07-02", source="capture"),
    )
    store.save_session(sess)

    # Count enrich_session calls with a NON-raising spy: a raising spy would be
    # swallowed by the production `except Exception` guard and give a false pass
    # (see memory: spy-raise-defeated-by-broad-except). The fast-fail must return
    # BEFORE any enrich work.
    calls = {"n": 0}
    monkeypatch.setattr(
        "transcripts.enrich.enrich_session",
        lambda *a, **k: (calls.__setitem__("n", calls["n"] + 1), sess)[1],
    )
    tr._enrich_in_background("empty-1")

    # (a) terminal failed status, (b) enrich never ran, (c) the fast-fail returned
    # before the v2-draft build (so no v2 draft exists) — three independent signals.
    assert store.load_session("empty-1").metadata.enrichment_status == "failed"
    assert calls["n"] == 0
    assert store.load_v2("empty-1") is None
