"""Server-side session tokens for cookie-based login.

Opaque tokens (not JWT) — stored in the `sessions` table (Alembic 0003).
Server-side storage lets logout actually revoke (delete the row); JWT can't.

Design rules:
- Token: 32 url-safe random bytes (`secrets.token_urlsafe(32)`). ~256 bits.
- TTL: 30 days. Rolling refresh — if a request comes in within 7 days of
  expiry, extend by 30 days. Keeps active users logged in without forcing
  re-auth, while inactive sessions naturally expire.
- Cookie: `conclave_session`, httpOnly, SameSite=Lax. `Secure` only when
  the request host isn't localhost (dev pragmatism).
- Bearer fallback: `Authorization: Bearer <token>` works for non-browser
  clients (curl, future CLI). Same token format.

`try_current_user(request)` returns the resolved User dict or None.
`require_current_user(request)` is the FastAPI dependency for protected
routes — 401s on missing/invalid.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Request, Response

from config import settings
from infra import identity
from storage.sqlite import _get_conn

COOKIE_NAME = "conclave_session"
_TTL_DAYS = 30
_REFRESH_WITHIN_DAYS = 7


def _iso(dt: datetime) -> str:
    return dt.isoformat() + "Z"


def _parse_iso(s: str) -> datetime:
    # Strip trailing 'Z' if present; sqlite stores naive UTC isoformat.
    return datetime.fromisoformat(s.rstrip("Z"))


def _now() -> datetime:
    return datetime.utcnow()


def issue_session(user_id: str) -> str:
    """Mint a new session token for `user_id`. Returns the opaque token string."""
    token = secrets.token_urlsafe(32)
    now = _now()
    expires = now + timedelta(days=_TTL_DAYS)
    _get_conn().execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at, last_seen_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (token, user_id, _iso(now), _iso(expires), _iso(now)),
    )
    return token


def revoke_session(token: str) -> None:
    """Delete the session row. Idempotent — no error if already gone."""
    _get_conn().execute("DELETE FROM sessions WHERE token = ?", (token,))


def revoke_all_sessions_for_user(user_id: str) -> int:
    """Force-logout everywhere. Returns row count deleted."""
    cur = _get_conn().execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    return cur.rowcount or 0


def _resolve_token(token: str) -> Optional[dict]:
    """Validate a token: not expired, user still exists. Applies rolling refresh.

    Returns the User dict (joined from `users`) or None if invalid/expired.
    """
    row = _get_conn().execute(
        "SELECT user_id, expires_at FROM sessions WHERE token = ?",
        (token,),
    ).fetchone()
    if row is None:
        return None

    now = _now()
    expires_at = _parse_iso(row["expires_at"])
    if now >= expires_at:
        # Lazy cleanup of an expired row keeps the table small over time.
        _get_conn().execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None

    # Rolling refresh: extend if we're within REFRESH_WITHIN_DAYS of expiry.
    if expires_at - now <= timedelta(days=_REFRESH_WITHIN_DAYS):
        new_expires = now + timedelta(days=_TTL_DAYS)
        _get_conn().execute(
            "UPDATE sessions SET expires_at = ?, last_seen_at = ? WHERE token = ?",
            (_iso(new_expires), _iso(now), token),
        )
    else:
        _get_conn().execute(
            "UPDATE sessions SET last_seen_at = ? WHERE token = ?",
            (_iso(now), token),
        )

    user = identity.get_user(row["user_id"])
    if user is None:
        # Orphaned session — user row got deleted. Clean up.
        _get_conn().execute("DELETE FROM sessions WHERE token = ?", (token,))
        return None
    return user


def _extract_token(request: Request) -> Optional[str]:
    """Prefer cookie; fall back to `Authorization: Bearer <token>` for CLI clients."""
    cookie = request.cookies.get(COOKIE_NAME)
    if cookie:
        return cookie
    auth = request.headers.get("authorization") or request.headers.get("Authorization")
    if auth and auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return None


def try_current_user(request: Request) -> Optional[dict]:
    """Return the authenticated User dict, or None if the request is anonymous."""
    token = _extract_token(request)
    if not token:
        return None
    return _resolve_token(token)


def require_current_user(request: Request) -> dict:
    """FastAPI dependency for protected routes."""
    user = try_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(request: Request) -> dict:
    """FastAPI dependency for admin-only routes.

    Admin identity is config-pinned (CONCLAVE_ADMIN_EMAILS), not a DB role —
    the allowlist is evaluated inside the enclave against the logged-in session
    email. 401 if unauthenticated, 403 if authenticated but not an admin.
    """
    user = require_current_user(request)
    if not settings.is_admin(user.get("email")):
        raise HTTPException(status_code=403, detail="admin access required")
    return user


# --- Cookie helpers ---------------------------------------------------------


def _is_secure_request(request: Optional[Request]) -> bool:
    """Mark cookies Secure only when the request itself is HTTPS.

    Scheme is the correct signal — hostname-based detection misses cases
    like reverse-proxied https on a non-standard host, and breaks
    starlette's TestClient which uses `http://testserver`.
    """
    if request is None:
        return False
    return (request.url.scheme or "").lower() == "https"


def set_session_cookie(
    response: Response,
    token: str,
    request: Optional[Request] = None,
) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=_TTL_DAYS * 24 * 3600,
        httponly=True,
        secure=_is_secure_request(request),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(
    response: Response,
    request: Optional[Request] = None,
) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        secure=_is_secure_request(request),
        samesite="lax",
    )
