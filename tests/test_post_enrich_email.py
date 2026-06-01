"""Tests for the post-enrichment magic-link blast (_send_attendee_magic_links).

Resend is in stub mode (no RESEND_API_KEY); we observe the calls via a
spy installed on the email module.
"""
from __future__ import annotations

import pytest

from api.transcripts_routes import _send_attendee_magic_links
from infra import identity, workspaces, magic_links
from storage import sqlite as _sqlite
from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean():
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM transcript_sessions")
    _get_conn().execute("DELETE FROM magic_links")
    reset_workspace_domain_tables()
    yield


def _make_session(*, session_id: str = "s1") -> None:
    _sqlite.save_transcript_session(
        session_id=session_id,
        source="recato",
        session_date="2026-06-01",
        raw_diarization=[],
        metadata={"date": "2026-06-01", "source": "recato"},
        derived={"summary": "Quarterly review with the new dashboard."},
    )


@pytest.fixture
def email_spy(monkeypatch):
    calls: list[dict] = []
    import infra.email as email_mod

    def _spy(**kwargs):
        calls.append(kwargs)
        return {"stub": True, **kwargs}

    monkeypatch.setattr(email_mod, "send_magic_link", _spy)
    # Also patch the bound symbol in api.transcripts_routes (it imports the
    # module by name and uses email_mod.send_magic_link — patching the
    # underlying module attribute is enough).
    return calls


def test_no_op_when_session_has_no_workspace(email_spy):
    _make_session()
    _send_attendee_magic_links("s1")
    assert email_spy == []


def test_no_op_when_visibility_owner_only(email_spy):
    owner = identity.upsert_user_by_supabase("sb-o", "owner@example.com")
    ws = workspaces.create_workspace("WS", owner["id"])
    _make_session()
    _sqlite.set_transcript_workspace(
        "s1", workspace_id=ws["id"], owner_user_id=owner["id"], visibility="owner-only"
    )
    workspaces.add_meeting_share("s1", "guest@example.com", owner["id"])
    _send_attendee_magic_links("s1")
    assert email_spy == []


def test_sends_to_each_attendee_when_shared(email_spy):
    owner = identity.upsert_user_by_supabase("sb-o", "owner@example.com")
    ws = workspaces.create_workspace("WS", owner["id"])
    _make_session()
    _sqlite.set_transcript_workspace(
        "s1", workspace_id=ws["id"], owner_user_id=owner["id"], visibility="shared"
    )
    workspaces.add_meeting_share("s1", "bob@example.com", owner["id"])
    workspaces.add_meeting_share("s1", "carol@example.com", owner["id"])

    _send_attendee_magic_links("s1")

    recipients = sorted(c["recipient_email"] for c in email_spy)
    assert recipients == ["bob@example.com", "carol@example.com"]
    # Magic links got issued — one per recipient.
    rows = _get_conn().execute(
        "SELECT user_email FROM magic_links WHERE meeting_session_id = ?", ("s1",)
    ).fetchall()
    assert {r["user_email"] for r in rows} == {"bob@example.com", "carol@example.com"}


def test_owner_never_emailed(email_spy):
    owner = identity.upsert_user_by_supabase("sb-o", "owner@example.com")
    ws = workspaces.create_workspace("WS", owner["id"])
    _make_session()
    _sqlite.set_transcript_workspace(
        "s1", workspace_id=ws["id"], owner_user_id=owner["id"], visibility="shared"
    )
    # Owner's own email accidentally in shares — defensive de-dup.
    workspaces.add_meeting_share("s1", "owner@example.com", owner["id"])
    workspaces.add_meeting_share("s1", "bob@example.com", owner["id"])

    _send_attendee_magic_links("s1")
    recipients = [c["recipient_email"] for c in email_spy]
    assert recipients == ["bob@example.com"]


def test_idempotent_on_re_run(email_spy):
    owner = identity.upsert_user_by_supabase("sb-o", "owner@example.com")
    ws = workspaces.create_workspace("WS", owner["id"])
    _make_session()
    _sqlite.set_transcript_workspace(
        "s1", workspace_id=ws["id"], owner_user_id=owner["id"], visibility="shared"
    )
    workspaces.add_meeting_share("s1", "bob@example.com", owner["id"])

    _send_attendee_magic_links("s1")
    _send_attendee_magic_links("s1")  # re-enrichment hits this again
    assert len(email_spy) == 1  # bob mailed once
    # One token per recipient — re-runs don't spawn new tokens.
    rows = _get_conn().execute(
        "SELECT COUNT(*) AS n FROM magic_links WHERE meeting_session_id = ?",
        ("s1",),
    ).fetchone()
    assert rows["n"] == 1


def test_meeting_title_set_from_summary(email_spy):
    owner = identity.upsert_user_by_supabase("sb-o", "owner@example.com")
    ws = workspaces.create_workspace("WS", owner["id"])
    _make_session()
    _sqlite.set_transcript_workspace(
        "s1", workspace_id=ws["id"], owner_user_id=owner["id"], visibility="shared"
    )
    workspaces.add_meeting_share("s1", "bob@example.com", owner["id"])
    _send_attendee_magic_links("s1")
    call = email_spy[0]
    assert call["meeting_title"].startswith("Quarterly review")
    assert call["inviter_email"] == "owner@example.com"
    # URL points at our magic-link route.
    assert "/m/" in call["magic_link_url"]
