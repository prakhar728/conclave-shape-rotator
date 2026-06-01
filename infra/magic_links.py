"""Single-use sign-in tokens emailed to meeting attendees.

Backed by the `magic_links` table (Alembic 0002):
  token PK, user_email, meeting_session_id, expires_at, consumed_at, created_at

Lifecycle:
  - `issue(email, meeting_session_id, ttl_days=7)` → opaque token string
  - `resolve(token)` → row dict if valid (not consumed, not expired), else None
  - `consume(token)` → marks consumed_at = now. Once consumed, a re-resolve
    still returns the row (so the page can read the bound meeting), but
    a fresh `consume` is a no-op. Single-use is enforced by the email
    flow, not by hard-deleting the row.

Why opaque (not JWT): same reasoning as auth sessions — server-side
revocation matters more than statelessness here. Plus we want to
distinguish "consumed once already" from "never seen" for analytics.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from storage.sqlite import _get_conn, _now

_DEFAULT_TTL_DAYS = 7


def _iso(dt: datetime) -> str:
    return dt.isoformat() + "Z"


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.rstrip("Z"))


def issue(
    *,
    user_email: str,
    meeting_session_id: Optional[str],
    ttl_days: int = _DEFAULT_TTL_DAYS,
) -> str:
    """Mint a new magic-link token. Returns the URL-safe token string."""
    token = secrets.token_urlsafe(32)
    now = datetime.utcnow()
    expires = now + timedelta(days=ttl_days)
    _get_conn().execute(
        "INSERT INTO magic_links (token, user_email, meeting_session_id, "
        "expires_at, consumed_at, created_at) VALUES (?, ?, ?, ?, NULL, ?)",
        (token, user_email, meeting_session_id, _iso(expires), _iso(now)),
    )
    return token


def resolve(token: str) -> Optional[dict]:
    """Return the row if valid (not expired), else None.

    Note: consumed-once links still resolve — the recipient can refresh the
    landing page without losing access. Single-use semantics live at the
    sign-in level (the OTP login flow doesn't re-grant access; the share
    table backfill in 2.11 is idempotent).
    """
    row = _get_conn().execute(
        "SELECT token, user_email, meeting_session_id, expires_at, "
        "consumed_at, created_at FROM magic_links WHERE token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None
    if datetime.utcnow() >= _parse_iso(row["expires_at"]):
        return None
    return dict(row)


def consume(token: str) -> Optional[dict]:
    """Mark a token consumed. Returns the row (or None if invalid)."""
    row = resolve(token)
    if row is None:
        return None
    if row["consumed_at"] is None:
        now = _now()
        _get_conn().execute(
            "UPDATE magic_links SET consumed_at = ? WHERE token = ?",
            (now, token),
        )
        row["consumed_at"] = now
    return row


def base_url() -> str:
    """Where magic links point. Read from BASE_URL env, with sensible dev default."""
    import os
    return os.environ.get("BASE_URL", "http://localhost:3001").rstrip("/")


def url_for(token: str) -> str:
    """Public URL the recipient sees in their inbox."""
    return f"{base_url()}/m/{token}"
