"""Google Calendar integration — dedicated OAuth, token store, and API client.

This module is the only place in the codebase that talks to Google's OAuth
and Calendar REST endpoints. It deliberately uses plain `httpx` (no Google
SDK) to match the lightweight style of `infra/github_app.py`.

Layers (built across the feature's steps):
  - Token store: encrypted-at-rest persistence of per-user OAuth tokens
    (`google_oauth_tokens`). Tokens are encrypted with `infra.crypto`
    before they ever touch SQLite.
  - OAuth flow: consent-URL build, code→token exchange, refresh.
  - Calendar client: list/create events, Meet-code extraction.

When the integration is unconfigured (`settings.google_calendar_enabled()`
is False), callers should 503 before reaching here; the token store still
guards independently by refusing to write without an encryption key.
"""
from __future__ import annotations

from typing import Optional

from infra import crypto
from storage.sqlite import _get_conn, _now

# --- OAuth constants --------------------------------------------------------
# Scopes: read events (list/auto-dispatch) + manage events (create/schedule).
SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
    "openid",
    "email",
]


# ---------------------------------------------------------------------------
# Token store (encrypted at rest)
# ---------------------------------------------------------------------------
def save_tokens(
    *,
    user_id: str,
    access_token: Optional[str],
    refresh_token: Optional[str],
    expiry: Optional[str],
    scopes: str = "",
) -> None:
    """Upsert a user's Google tokens, encrypting both before write.

    Google only returns a refresh_token on the *first* consent (or when
    prompt=consent forces re-issue). On a plain refresh we get a new access
    token but no refresh token — so a None `refresh_token` here means "keep
    the one already stored" rather than wiping it.

    Raises crypto.TokenEncryptionUnavailable if no encryption key is set —
    callers treat that as 'integration not configured'.
    """
    access_enc = crypto.encrypt(access_token) if access_token else None
    refresh_enc = crypto.encrypt(refresh_token) if refresh_token else None
    now = _now()
    conn = _get_conn()
    existing = conn.execute(
        "SELECT refresh_token_enc, connected_at FROM google_oauth_tokens WHERE user_id = ?",
        (user_id,),
    ).fetchone()

    if existing is None:
        conn.execute(
            "INSERT INTO google_oauth_tokens "
            "(user_id, access_token_enc, refresh_token_enc, expiry, scopes, "
            " connected_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, access_enc, refresh_enc, expiry, scopes, now, now),
        )
        return

    # Preserve the prior refresh token when this call didn't carry one.
    if refresh_enc is None:
        refresh_enc = existing["refresh_token_enc"]
    conn.execute(
        "UPDATE google_oauth_tokens SET access_token_enc = ?, refresh_token_enc = ?, "
        "expiry = ?, scopes = ?, updated_at = ? WHERE user_id = ?",
        (access_enc, refresh_enc, expiry, scopes, now, user_id),
    )


def get_tokens(user_id: str) -> Optional[dict]:
    """Return decrypted tokens for a user, or None if not connected.

    Shape: {access_token, refresh_token, expiry, scopes, connected_at,
    updated_at}. Decryption failures (rotated key) raise
    crypto.TokenEncryptionUnavailable — caller should prompt reconnect.
    """
    row = _get_conn().execute(
        "SELECT access_token_enc, refresh_token_enc, expiry, scopes, "
        "connected_at, updated_at FROM google_oauth_tokens WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "access_token": crypto.decrypt(row["access_token_enc"]) if row["access_token_enc"] else None,
        "refresh_token": crypto.decrypt(row["refresh_token_enc"]) if row["refresh_token_enc"] else None,
        "expiry": row["expiry"],
        "scopes": row["scopes"],
        "connected_at": row["connected_at"],
        "updated_at": row["updated_at"],
    }


def is_connected(user_id: str) -> bool:
    """Cheap connection probe — does NOT decrypt (so it works even if the
    encryption key was rotated)."""
    row = _get_conn().execute(
        "SELECT 1 FROM google_oauth_tokens WHERE user_id = ? AND refresh_token_enc IS NOT NULL",
        (user_id,),
    ).fetchone()
    return row is not None


def delete_tokens(user_id: str) -> None:
    """Disconnect: drop the user's stored tokens. Idempotent."""
    _get_conn().execute(
        "DELETE FROM google_oauth_tokens WHERE user_id = ?", (user_id,)
    )


def list_connected_user_ids() -> list[str]:
    """All users with a usable (refresh-token-bearing) Google connection.
    The auto-dispatch poller iterates these."""
    rows = _get_conn().execute(
        "SELECT user_id FROM google_oauth_tokens WHERE refresh_token_enc IS NOT NULL"
    ).fetchall()
    return [r["user_id"] for r in rows]
