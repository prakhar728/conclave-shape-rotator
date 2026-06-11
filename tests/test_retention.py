"""Transcript Saving — retention / auto-delete (Phase 2).

Covers the pure decision functions and the end-to-end sweep:
  - effective_retention_days precedence (override vs account default)
  - is_expired boundary
  - run_retention_sweep purges ONLY expired sessions, keeps derived/summary,
    is idempotent, and honors keep_forever / per-meeting-days / account-default
  - account settings round-trip (identity layer)

The sweep takes an injectable `now`, so tests simulate the passage of time by
passing a future `now` rather than backdating rows.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from infra import identity, workspaces
from transcripts import retention, store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


@pytest.fixture(autouse=True)
def _clean_tables():
    from tests.conftest import reset_workspace_domain_tables
    reset_workspace_domain_tables()
    from storage.sqlite import _get_conn
    _get_conn().execute("DELETE FROM transcript_sessions")
    yield


# --- Pure decision functions ------------------------------------------------

def test_effective_days_keep_forever_override_wins():
    assert retention.effective_retention_days("keep_forever", 30) is None


def test_effective_days_numeric_override_wins_over_account():
    assert retention.effective_retention_days("7", 30) == 7


def test_effective_days_inherits_account_default_when_no_override():
    assert retention.effective_retention_days(None, 90) == 90
    assert retention.effective_retention_days(None, None) is None


def test_effective_days_malformed_override_falls_back_to_account():
    # Errs toward keeping data: bad override → account default, not delete-now.
    assert retention.effective_retention_days("garbage", 30) == 30


def test_is_expired_boundary():
    created = "2026-01-01T00:00:00Z"
    base = datetime(2026, 1, 1)
    assert retention.is_expired(created, 10, base + timedelta(days=9)) is False
    assert retention.is_expired(created, 10, base + timedelta(days=10)) is True
    # None days = keep forever, never expires.
    assert retention.is_expired(created, None, base + timedelta(days=9999)) is False


# --- Sweep end-to-end -------------------------------------------------------

def _store_owned_session(sid: str, owner_id: str, ws_id: str) -> Session:
    sess = Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="A", text="raw secret words", start=0.0)],
        metadata=SessionMetadata(date="2026-05-20", source="otter"),
        derived=Derived(summary="kept summary"),
    )
    store.save_session(sess)
    store.set_workspace(sid, ws_id, owner_id, visibility="owner-only")
    return sess


@pytest.fixture
def alice() -> dict:
    return identity.upsert_user_by_supabase("sb-alice", "alice@example.com", "A")


@pytest.fixture
def ws(alice: dict) -> dict:
    return workspaces.create_workspace("Personal", alice["id"])


def test_sweep_purges_expired_keeps_summary(alice, ws):
    identity.set_user_settings(alice["id"], {"retention_days": 30})
    _store_owned_session("s1", alice["id"], ws["id"])

    # 31 days later → expired.
    future = datetime.utcnow() + timedelta(days=31)
    purged = retention.run_retention_sweep(now=future)
    assert purged == ["s1"]

    reloaded = store.load_session("s1")
    assert reloaded.raw_diarization == []          # raw gone
    assert reloaded.derived.summary == "kept summary"  # summary kept
    fields = store.get_workspace_fields("s1")
    assert fields["raw_transcript_deleted_at"] is not None


def test_sweep_keeps_unexpired(alice, ws):
    identity.set_user_settings(alice["id"], {"retention_days": 30})
    _store_owned_session("s1", alice["id"], ws["id"])

    # Only 10 days later → not expired.
    purged = retention.run_retention_sweep(now=datetime.utcnow() + timedelta(days=10))
    assert purged == []
    assert store.load_session("s1").raw_diarization != []


def test_account_default_none_keeps_forever(alice, ws):
    # No retention_days set → keep forever, even far in the future.
    _store_owned_session("s1", alice["id"], ws["id"])
    purged = retention.run_retention_sweep(now=datetime.utcnow() + timedelta(days=99999))
    assert purged == []


def test_keep_forever_override_beats_account_default(alice, ws):
    identity.set_user_settings(alice["id"], {"retention_days": 30})
    _store_owned_session("s1", alice["id"], ws["id"])
    store.set_retention_override("s1", "keep_forever")
    purged = retention.run_retention_sweep(now=datetime.utcnow() + timedelta(days=365))
    assert purged == []


def test_per_meeting_days_override_beats_account_default(alice, ws):
    # Account = keep forever, but this meeting overrides to 7 days.
    _store_owned_session("s1", alice["id"], ws["id"])
    store.set_retention_override("s1", "7")
    purged = retention.run_retention_sweep(now=datetime.utcnow() + timedelta(days=8))
    assert purged == ["s1"]


def test_sweep_is_idempotent(alice, ws):
    identity.set_user_settings(alice["id"], {"retention_days": 30})
    _store_owned_session("s1", alice["id"], ws["id"])
    future = datetime.utcnow() + timedelta(days=31)
    assert retention.run_retention_sweep(now=future) == ["s1"]
    # Second run: already purged → not returned again.
    assert retention.run_retention_sweep(now=future) == []


# --- Account settings round-trip -------------------------------------------

def test_account_retention_days_round_trip(alice):
    assert identity.get_account_retention_days(alice["id"]) is None  # default
    identity.set_user_settings(alice["id"], {"retention_days": 90})
    assert identity.get_account_retention_days(alice["id"]) == 90
    # Non-positive / bool junk reads as keep-forever.
    identity.set_user_settings(alice["id"], {"retention_days": 0})
    assert identity.get_account_retention_days(alice["id"]) is None
