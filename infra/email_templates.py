"""HTML email templates — plain, Proton-style.

Inlined CSS because most email clients strip <style>. Dark / light is
audience-controlled (most inboxes pick); colors here are designed to be
legible in either.

We send only the magic link in the email — no transcript content,
per BUILD_DOC §4 (Decision: transcripts never leave the enclave in
plaintext, even via email body). The recipient must click through and
authenticate to see the meeting.
"""
from __future__ import annotations

from typing import Optional

# Brand-neutral tokens (Proton-style minimal palette).
_BG = "#0a0a0a"
_CARD = "#171717"
_FG = "#fafafa"
_MUTED = "#a1a1aa"
_BORDER = "#27272a"
_PRIMARY = "#fafafa"
_PRIMARY_FG = "#0a0a0a"


def _shell(*, body_html: str, footer_html: str) -> str:
    """Outer email frame. Kept dead simple so it renders on any client."""
    return f"""\
<!doctype html>
<html lang="en">
<body style="margin:0;padding:0;background:{_BG};color:{_FG};font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{_BG};padding:40px 16px;">
    <tr>
      <td align="center">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
          <tr>
            <td style="padding:0 0 24px 0;">
              <span style="font-size:12px;letter-spacing:0.22em;text-transform:uppercase;color:{_MUTED};font-weight:600;">Conclave</span>
            </td>
          </tr>
          <tr>
            <td style="background:{_CARD};border:1px solid {_BORDER};border-radius:8px;padding:32px;">
              {body_html}
            </td>
          </tr>
          <tr>
            <td style="padding:24px 0 0 0;color:{_MUTED};font-size:12px;line-height:1.5;">
              {footer_html}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def _cta_button(url: str, label: str) -> str:
    return f"""\
<a href="{url}" style="display:inline-block;background:{_PRIMARY};color:{_PRIMARY_FG};padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:600;font-size:14px;">
  {label}
</a>"""


def magic_link_email(
    *,
    magic_link_url: str,
    meeting_title: Optional[str],
    inviter_email: Optional[str],
) -> str:
    title_block = (
        f"<h1 style='margin:0 0 16px 0;font-size:18px;font-weight:600;color:{_FG};'>"
        f"A new meeting was shared with you</h1>"
    )

    inviter_line = (
        f"<p style='margin:0 0 16px 0;font-size:14px;color:{_MUTED};'>"
        f"Shared by {inviter_email}.</p>"
        if inviter_email
        else ""
    )

    title_line = (
        f"<p style='margin:0 0 16px 0;font-size:14px;color:{_FG};'>"
        f"<strong>{meeting_title}</strong></p>"
        if meeting_title
        else ""
    )

    body_html = (
        title_block
        + inviter_line
        + title_line
        + f"<p style='margin:0 0 24px 0;font-size:14px;line-height:1.5;color:{_FG};'>"
        f"Click below to sign in and view the meeting. We don&apos;t include the "
        f"transcript in this email — Conclave only serves it after authentication.</p>"
        + _cta_button(magic_link_url, "View meeting")
        + f"<p style='margin:24px 0 0 0;font-size:12px;color:{_MUTED};word-break:break-all;'>"
        f"Or paste this link into your browser:<br>{magic_link_url}</p>"
    )
    footer_html = (
        "This link expires in 7 days. If you didn&apos;t expect this email, "
        "you can safely ignore it."
    )
    return _shell(body_html=body_html, footer_html=footer_html)


def feedback_email(
    *,
    category: str,
    body: str,
    submitter_email: str,
    page_context: Optional[str],
) -> str:
    """Team notification for one /feedback submission (Task #19).

    Body is user-supplied free text, so it's HTML-escaped before interpolation.
    """
    import html

    safe_body = html.escape(body).replace("\n", "<br>")
    safe_category = html.escape(category)
    safe_submitter = html.escape(submitter_email)
    context_line = (
        f"<p style='margin:0 0 16px 0;font-size:13px;color:{_MUTED};'>"
        f"From page: <code>{html.escape(page_context)}</code></p>"
        if page_context
        else ""
    )
    body_html = (
        f"<h1 style='margin:0 0 16px 0;font-size:18px;font-weight:600;color:{_FG};'>"
        f"New feedback: {safe_category}</h1>"
        f"<p style='margin:0 0 16px 0;font-size:14px;color:{_MUTED};'>"
        f"From {safe_submitter}</p>"
        + context_line
        + f"<div style='margin:0;padding:16px;background:{_BG};border:1px solid {_BORDER};"
        f"border-radius:8px;font-size:14px;line-height:1.5;color:{_FG};'>{safe_body}</div>"
    )
    footer_html = "Sent by Conclave when a user submits in-app feedback."
    return _shell(body_html=body_html, footer_html=footer_html)


def welcome_email(*, recipient_email: str) -> str:
    body_html = (
        f"<h1 style='margin:0 0 16px 0;font-size:18px;font-weight:600;color:{_FG};'>"
        f"Welcome to Conclave</h1>"
        f"<p style='margin:0 0 16px 0;font-size:14px;color:{_FG};line-height:1.5;'>"
        f"Your account is set up. Conclave gives you confidential transcription "
        f"and signal extraction for every meeting you invite our bot to — "
        f"transcription runs inside a TEE, so the operator can&apos;t read it.</p>"
        f"<p style='margin:0 0 24px 0;font-size:14px;color:{_FG};'>"
        f"Sign in to your dashboard to invite the bot to your next call.</p>"
        + _cta_button("https://example.com/dashboard", "Open Conclave")
    )
    footer_html = f"You signed up as {recipient_email}."
    return _shell(body_html=body_html, footer_html=footer_html)
