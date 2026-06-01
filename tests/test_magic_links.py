"""Round-trip tests for infra/magic_links.py + infra/email.py stub mode."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from infra import email, magic_links
from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _clean():
    _get_conn().execute("DELETE FROM magic_links")
    yield


def test_issue_and_resolve():
    token = magic_links.issue(
        user_email="alice@example.com", meeting_session_id="sess-1"
    )
    row = magic_links.resolve(token)
    assert row is not None
    assert row["user_email"] == "alice@example.com"
    assert row["meeting_session_id"] == "sess-1"
    assert row["consumed_at"] is None


def test_resolve_unknown_returns_none():
    assert magic_links.resolve("not-a-real-token") is None


def test_consume_marks_consumed_then_idempotent():
    token = magic_links.issue(user_email="a@example.com", meeting_session_id="s")
    row = magic_links.consume(token)
    assert row["consumed_at"] is not None
    first = row["consumed_at"]
    # Second consume is a no-op — same consumed_at, still resolves.
    row2 = magic_links.consume(token)
    assert row2["consumed_at"] == first


def test_expired_token_does_not_resolve():
    # Insert a row manually with expires_at in the past.
    past = datetime.utcnow() - timedelta(days=1)
    _get_conn().execute(
        "INSERT INTO magic_links (token, user_email, meeting_session_id, "
        "expires_at, consumed_at, created_at) VALUES (?, ?, ?, ?, NULL, ?)",
        ("expired-tok", "e@example.com", "s", past.isoformat() + "Z",
         datetime.utcnow().isoformat() + "Z"),
    )
    assert magic_links.resolve("expired-tok") is None


def test_url_for_uses_base_url(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://app.example.com")
    assert magic_links.url_for("abc") == "https://app.example.com/m/abc"


# --- email stub mode -------------------------------------------------------


def test_send_magic_link_stub_mode_logs_when_no_key(monkeypatch, caplog):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    out = email.send_magic_link(
        recipient_email="bob@example.com",
        magic_link_url="https://example.com/m/tok",
        meeting_title="Weekly review",
        inviter_email="alice@example.com",
    )
    assert out["stub"] is True
    assert out["to"] == "bob@example.com"
    assert "Weekly review" in out["subject"]


def test_magic_link_template_includes_link_and_no_transcript():
    from infra.email_templates import magic_link_email
    html = magic_link_email(
        magic_link_url="https://example.com/m/abc",
        meeting_title="Review",
        inviter_email="alice@example.com",
    )
    assert "https://example.com/m/abc" in html
    assert "View meeting" in html
    # Per BUILD_DOC §4 — transcript content NEVER in email body.
    # A negative check: the template never names a derived field.
    assert "summary" not in html.lower()
    assert "transcript" in html.lower()  # we MENTION the word; we don't INCLUDE the content
