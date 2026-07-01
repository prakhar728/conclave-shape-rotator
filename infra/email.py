"""Transactional email via Resend.

Two paths:
- `RESEND_API_KEY` present → real send.
- `RESEND_API_KEY` unset    → stub mode. Logs the would-be email payload
                              and records it in the `magic_links` row's
                              audit trail (consumer can read `consumed_at`
                              etc.). Dev / CI default.

Stub mode is the right default: Phase 1 + 2 development doesn't need a
real Resend account, and never-sending-real-emails is the safer wrong
answer if a key is forgotten. Logs are explicit ("STUB EMAIL …") so it's
obvious which mode you're in.

BUILD_DOC §4 D-resend: free tier 3K/mo is plenty for v1.
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from infra.email_templates import (
    feedback_email,
    magic_link_email,
    welcome_email,
    workspace_invite_email,
)

logger = logging.getLogger(__name__)


class EmailSendError(Exception):
    """Resend returned a non-2xx or the SDK raised."""


def _api_key() -> Optional[str]:
    return os.environ.get("RESEND_API_KEY") or None


def _sender() -> str:
    return os.environ.get(
        "RESEND_SENDER_EMAIL", "Conclave <onboarding@resend.dev>"
    )


def _send(*, to: str, subject: str, html: str) -> dict:
    """Lowest-level dispatch. Real send when key present; logs otherwise."""
    api_key = _api_key()
    if not api_key:
        logger.warning(
            "STUB EMAIL — would have sent to %s: subject=%r len=%d",
            to,
            subject,
            len(html),
        )
        return {"stub": True, "to": to, "subject": subject}

    try:
        import resend  # type: ignore[import-untyped]
        resend.api_key = api_key
        result = resend.Emails.send(
            {
                "from": _sender(),
                "to": [to],
                "subject": subject,
                "html": html,
            }
        )
    except Exception as e:  # noqa: BLE001 — Resend SDK exceptions vary
        raise EmailSendError(f"Resend send failed: {e}") from e
    return result if isinstance(result, dict) else {"id": str(result)}


# --- Typed senders (used by routes / background tasks) --------------------


def send_magic_link(
    *,
    recipient_email: str,
    magic_link_url: str,
    meeting_title: Optional[str],
    inviter_email: Optional[str] = None,
) -> dict:
    """Email a one-tap sign-in link tied to a specific meeting."""
    subject = (
        f"Conclave: {meeting_title}"
        if meeting_title
        else "Conclave: a new meeting was shared with you"
    )
    html = magic_link_email(
        magic_link_url=magic_link_url,
        meeting_title=meeting_title,
        inviter_email=inviter_email,
    )
    return _send(to=recipient_email, subject=subject, html=html)


def send_workspace_invite(
    *,
    recipient_email: str,
    accept_url: str,
    workspace_name: Optional[str] = None,
    inviter_email: Optional[str] = None,
) -> dict:
    """Email a workspace-invite accept link (Task #32). Callers wrap in best-effort
    try/except — a failed send must never lose the invite. Stub-mode just logs."""
    subject = (
        f"Conclave: you're invited to {workspace_name}"
        if workspace_name
        else "Conclave: you're invited to a workspace"
    )
    html = workspace_invite_email(
        accept_url=accept_url,
        workspace_name=workspace_name,
        inviter_email=inviter_email,
    )
    return _send(to=recipient_email, subject=subject, html=html)


def send_feedback_notification(
    *,
    recipient_email: str,
    category: str,
    body: str,
    submitter_email: str,
    page_context: Optional[str] = None,
) -> dict:
    """Notify the team that a user submitted in-app feedback (Task #19).

    Callers wrap this in best-effort try/except — a failed send must never block
    the feedback submission. Stub-mode (no RESEND_API_KEY) just logs.
    """
    subject = f"Conclave feedback ({category}) from {submitter_email}"
    html = feedback_email(
        category=category,
        body=body,
        submitter_email=submitter_email,
        page_context=page_context,
    )
    return _send(to=recipient_email, subject=subject, html=html)


def send_welcome(recipient_email: str) -> dict:
    """First-signup welcome (currently unused; reserved for 2.11+ flow polish)."""
    html = welcome_email(recipient_email=recipient_email)
    return _send(
        to=recipient_email,
        subject="Welcome to Conclave",
        html=html,
    )
