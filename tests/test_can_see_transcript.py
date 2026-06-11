"""Transcript Saving — the raw-transcript gate `can_see_transcript`.

Stricter than `can_user_see`: a 'summary_only' recipient passes `can_user_see`
(they get the derived summary) but must FAIL here so the raw transcript stays
withheld. Mirrors the table-driven style of test_can_user_see.py and reuses the
same workspace-domain reset fixture.
"""
from __future__ import annotations

import pytest

from api.transcripts_routes import can_see_transcript, can_user_see
from infra import identity, workspaces


@pytest.fixture(autouse=True)
def _clean_tables():
    from tests.conftest import reset_workspace_domain_tables
    reset_workspace_domain_tables()
    yield


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


def test_owner_always_sees_transcript(alice, bob, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="owner-only")
    assert can_see_transcript(alice, row) is True
    assert can_see_transcript(bob, row) is False
    assert can_see_transcript(None, row) is False


def test_summary_only_recipient_denied_transcript(alice, bob, ws):
    """The crux: summary_only sees the summary (can_user_see) but NOT raw."""
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    workspaces.add_meeting_share(
        row["session_id"], bob["email"], alice["id"], scope="summary_only"
    )
    # Bob can see the derived view…
    assert can_user_see(bob, row) is True
    # …but NOT the raw transcript.
    assert can_see_transcript(bob, row) is False


def test_summary_and_transcript_recipient_sees_transcript(alice, bob, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    workspaces.add_meeting_share(
        row["session_id"], bob["email"], alice["id"], scope="summary_and_transcript"
    )
    assert can_see_transcript(bob, row) is True


def test_default_share_scope_grants_transcript(alice, bob, ws):
    """Pre-0011 rows (and shares added without an explicit scope) default to
    summary_and_transcript, preserving the old 'shared = full access'."""
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    workspaces.add_meeting_share(row["session_id"], bob["email"], alice["id"])
    assert can_see_transcript(bob, row) is True


def test_non_shared_user_denied(alice, bob, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    # No share for bob at all.
    assert can_see_transcript(bob, row) is False


def test_workspace_member_sees_transcript(alice, bob, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="workspace")
    assert can_see_transcript(bob, row) is False  # not a member yet
    from storage.sqlite import _get_conn, _now
    _get_conn().execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role, added_at, added_by) "
        "VALUES (?, ?, 'member', ?, ?)",
        (ws["id"], bob["id"], _now(), alice["id"]),
    )
    assert can_see_transcript(bob, row) is True


def test_public_link_and_anonymous_denied(alice, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="public-link")
    assert can_see_transcript(None, row) is False
    other = identity.upsert_user_by_supabase("sb-o", "o@example.com", "O")
    assert can_see_transcript(other, row) is False
