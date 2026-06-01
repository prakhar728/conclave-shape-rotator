"""Phase 1.7 — workspace-aware can_user_see.

Doesn't touch the legacy cohort path — that's covered by the existing
test_api_transcripts.py tests, which still pass unchanged.
"""
from __future__ import annotations

import pytest

from api.transcripts_routes import can_user_see
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


def _row(
    *,
    workspace_id: str | None,
    owner_user_id: str | None,
    visibility: str,
    session_id: str = "sess-1",
) -> dict:
    return {
        "session_id": session_id,
        "workspace_id": workspace_id,
        "owner_user_id": owner_user_id,
        "visibility": visibility,
    }


def test_owner_only_grants_owner_blocks_others(alice, bob, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="owner-only")
    assert can_user_see(alice, row) is True
    assert can_user_see(bob, row) is False
    assert can_user_see(None, row) is False


def test_shared_requires_explicit_meeting_share(alice, bob, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    # Owner always sees.
    assert can_user_see(alice, row) is True
    # Bob without a share → False.
    assert can_user_see(bob, row) is False
    # Add a share for Bob's email → True.
    workspaces.add_meeting_share(row["session_id"], bob["email"], alice["id"])
    assert can_user_see(bob, row) is True


def test_shared_blocks_anonymous(alice, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="shared")
    assert can_user_see(None, row) is False


def test_workspace_visibility_grants_any_member(alice, bob, ws):
    # Bob isn't a member of ws by default.
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="workspace")
    assert can_user_see(alice, row) is True   # owner
    assert can_user_see(bob, row) is False    # non-member
    # Hand-add bob as a member (v1.5 surface, but the underlying check works).
    from storage.sqlite import _get_conn, _now
    _get_conn().execute(
        "INSERT INTO workspace_members (workspace_id, user_id, role, added_at, added_by) "
        "VALUES (?, ?, 'member', ?, ?)",
        (ws["id"], bob["id"], _now(), alice["id"]),
    )
    assert can_user_see(bob, row) is True


def test_public_link_blocked_in_v1(alice, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="public-link")
    # Even owner gets False — public-link plumbing isn't wired in v1.
    # (Owner check happens before this branch, so owner DOES see; non-owner doesn't.)
    # Actually let's verify documented behavior: anonymous + non-owner blocked.
    assert can_user_see(None, row) is False
    # Non-owner blocked too.
    other = identity.upsert_user_by_supabase("sb-other", "o@example.com", "O")
    assert can_user_see(other, row) is False


def test_unknown_visibility_defensive_false(alice, ws):
    row = _row(workspace_id=ws["id"], owner_user_id=alice["id"], visibility="future-mode")
    # Owner still wins via the owner check.
    assert can_user_see(alice, row) is True
    other = identity.upsert_user_by_supabase("sb-other", "o@example.com", "O")
    assert can_user_see(other, row) is False


def test_no_owner_set_owner_only_blocks_everyone(alice, ws):
    """Defensive: row with owner_user_id NULL + owner-only → no one passes."""
    row = _row(workspace_id=ws["id"], owner_user_id=None, visibility="owner-only")
    assert can_user_see(alice, row) is False
    assert can_user_see(None, row) is False


def test_can_see_dispatch_legacy_path_unchanged():
    """The legacy can_see signature still works when no row is passed."""
    from api.transcripts_routes import can_see
    from transcripts.models import Session, SessionMetadata, Derived

    sess = Session(
        session_id="legacy-1",
        raw_diarization=[],
        metadata=SessionMetadata(
            date="2026-06-01",
            source="test",
            visibility="cohort",
        ),
        derived=Derived(),
    )
    # No row → legacy cohort logic → everyone allowed.
    assert can_see(None, sess) is True
    assert can_see("any-record-id", sess) is True


def test_can_see_dispatch_routes_to_workspace_mode_when_row_present(alice, ws):
    from api.transcripts_routes import can_see
    from transcripts.models import Session, SessionMetadata, Derived

    sess = Session(
        session_id="ws-sess-1",
        raw_diarization=[],
        metadata=SessionMetadata(date="2026-06-01", source="test"),
        derived=Derived(),
    )
    row = _row(
        workspace_id=ws["id"],
        owner_user_id=alice["id"],
        visibility="owner-only",
        session_id="ws-sess-1",
    )
    # Workspace mode kicks in — viewer must be a User dict.
    assert can_see(alice, sess, row) is True
    assert can_see(None, sess, row) is False
    # String viewer in workspace mode → treated as no auth.
    assert can_see("some-record-id", sess, row) is False
