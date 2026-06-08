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

import base64
import hashlib
import hmac
import json
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urlencode

import httpx

from config import settings
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

_AUTH_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"
_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
# Refresh this many seconds BEFORE the recorded expiry, so a token that's
# about to lapse mid-request gets refreshed proactively.
_EXPIRY_SKEW_S = 60


class GoogleOAuthError(Exception):
    """Google's OAuth/token endpoint returned a non-2xx or was unreachable."""


class GoogleCalendarError(Exception):
    """The Calendar REST API returned a non-2xx or was unreachable."""


# ---------------------------------------------------------------------------
# OAuth `state` — CSRF-safe, identity-bearing
# ---------------------------------------------------------------------------
# We sign {user_id, nonce, iat} with the same server-side key used for token
# encryption, so the callback can recover (and trust) which user initiated
# the connect WITHOUT relying solely on the session cookie surviving Google's
# cross-site redirect. Expires after 10 minutes.
_STATE_TTL_S = 600


def _state_key() -> bytes:
    key = settings.token_enc_key
    if not key:
        raise GoogleOAuthError("CONCLAVE_TOKEN_ENC_KEY required to sign OAuth state")
    return hashlib.sha256(key.encode()).digest()


def make_state(user_id: str) -> str:
    payload = {"uid": user_id, "n": secrets.token_hex(8), "iat": int(time.time())}
    raw = json.dumps(payload, separators=(",", ":")).encode()
    body = base64.urlsafe_b64encode(raw).decode().rstrip("=")
    sig = hmac.new(_state_key(), body.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{body}.{sig}"


def verify_state(state: str) -> str:
    """Return the user_id encoded in a valid, unexpired state. Raises
    GoogleOAuthError on tamper/expiry."""
    try:
        body, sig = state.split(".", 1)
    except ValueError as e:
        raise GoogleOAuthError("malformed state") from e
    expected = hmac.new(_state_key(), body.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        raise GoogleOAuthError("state signature mismatch")
    try:
        raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
        payload = json.loads(raw)
    except (ValueError, json.JSONDecodeError) as e:
        raise GoogleOAuthError("undecodable state") from e
    if int(time.time()) - int(payload.get("iat", 0)) > _STATE_TTL_S:
        raise GoogleOAuthError("state expired")
    uid = payload.get("uid")
    if not uid:
        raise GoogleOAuthError("state missing uid")
    return uid


# ---------------------------------------------------------------------------
# OAuth flow
# ---------------------------------------------------------------------------
def build_auth_url(state: str) -> str:
    """Build the Google consent URL.

    `access_type=offline` + `prompt=consent` ensures we get a refresh token
    (Google omits it on repeat consents unless forced), which the background
    auto-dispatch poller depends on. `state` is an opaque CSRF/identity token
    we mint and verify on callback.
    """
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "include_granted_scopes": "true",
        "prompt": "consent",
        "state": state,
    }
    return f"{_AUTH_ENDPOINT}?{urlencode(params)}"


def _expiry_iso(expires_in: Optional[int]) -> Optional[str]:
    if not expires_in:
        return None
    return (datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))).isoformat()


def exchange_code(code: str) -> dict:
    """Exchange an authorization code for tokens.

    Returns the raw Google token response augmented with `expiry` (ISO). The
    caller persists via `save_tokens`.
    """
    data = {
        "code": code,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "redirect_uri": settings.google_redirect_uri,
        "grant_type": "authorization_code",
    }
    try:
        resp = httpx.post(_TOKEN_ENDPOINT, data=data, timeout=20.0)
    except httpx.HTTPError as e:
        raise GoogleOAuthError(f"token endpoint unreachable: {e}") from e
    if resp.status_code >= 400:
        raise GoogleOAuthError(f"code exchange failed {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    body["expiry"] = _expiry_iso(body.get("expires_in"))
    return body


def refresh_access_token(refresh_token: str) -> dict:
    """Use a refresh token to mint a new access token. Returns Google's
    response with `expiry` (ISO) added. Note Google does NOT return a new
    refresh_token here — `save_tokens(refresh_token=None)` keeps the old one.
    """
    data = {
        "refresh_token": refresh_token,
        "client_id": settings.google_client_id,
        "client_secret": settings.google_client_secret,
        "grant_type": "refresh_token",
    }
    try:
        resp = httpx.post(_TOKEN_ENDPOINT, data=data, timeout=20.0)
    except httpx.HTTPError as e:
        raise GoogleOAuthError(f"token endpoint unreachable: {e}") from e
    if resp.status_code >= 400:
        raise GoogleOAuthError(f"refresh failed {resp.status_code}: {resp.text[:300]}")
    body = resp.json()
    body["expiry"] = _expiry_iso(body.get("expires_in"))
    return body


def _is_expired(expiry_iso: Optional[str]) -> bool:
    if not expiry_iso:
        return True  # unknown expiry → refresh to be safe
    try:
        exp = datetime.fromisoformat(expiry_iso)
    except ValueError:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= (exp - timedelta(seconds=_EXPIRY_SKEW_S))


def valid_access_token(user_id: str) -> str:
    """Return a currently-valid access token for the user, refreshing (and
    re-persisting) if the stored one is expired.

    Raises GoogleOAuthError if the user isn't connected or has no refresh
    token — caller should surface "reconnect Google Calendar".
    """
    tokens = get_tokens(user_id)
    if tokens is None:
        raise GoogleOAuthError("user has not connected Google Calendar")
    if tokens["access_token"] and not _is_expired(tokens["expiry"]):
        return tokens["access_token"]
    refresh = tokens["refresh_token"]
    if not refresh:
        raise GoogleOAuthError("no refresh token on file — user must reconnect")
    refreshed = refresh_access_token(refresh)
    new_access = refreshed.get("access_token")
    if not new_access:
        raise GoogleOAuthError("refresh response had no access_token")
    save_tokens(
        user_id=user_id,
        access_token=new_access,
        refresh_token=refreshed.get("refresh_token"),  # usually None → preserved
        expiry=refreshed.get("expiry"),
        scopes=tokens["scopes"],
    )
    return new_access


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


# ---------------------------------------------------------------------------
# Calendar API client
# ---------------------------------------------------------------------------
def extract_meet_code(event: dict) -> Optional[str]:
    """Pull the Google Meet code from an event, or None if it has no Meet.

    Checks `hangoutLink` first, then `conferenceData.entryPoints[*].uri`.
    Reuses the recato Meet-URL parser so the code shape matches what the bot
    launcher expects (abc-defg-hij)."""
    from connectors.recato.launch import parse_meet_input

    candidates = []
    if event.get("hangoutLink"):
        candidates.append(event["hangoutLink"])
    conf = event.get("conferenceData") or {}
    for ep in conf.get("entryPoints") or []:
        if ep.get("uri"):
            candidates.append(ep["uri"])
    for c in candidates:
        try:
            return parse_meet_input(c)
        except ValueError:
            continue
    return None


def _normalize_event(event: dict) -> dict:
    """Project Google's verbose event into the shape our API/poller use."""
    start = event.get("start") or {}
    end = event.get("end") or {}
    attendees = [
        a["email"] for a in (event.get("attendees") or []) if a.get("email")
    ]
    return {
        "id": event.get("id"),
        "title": event.get("summary") or "(no title)",
        "start": start.get("dateTime") or start.get("date"),
        "end": end.get("dateTime") or end.get("date"),
        "organizer": (event.get("organizer") or {}).get("email"),
        "attendees": attendees,
        "hangout_link": event.get("hangoutLink"),
        "meet_code": extract_meet_code(event),
        "html_link": event.get("htmlLink"),
    }


def _auth_headers(user_id: str) -> dict:
    return {
        "Authorization": f"Bearer {valid_access_token(user_id)}",
        "Accept": "application/json",
    }


def list_events(
    user_id: str,
    *,
    time_min: str,
    time_max: str,
    max_results: int = 50,
    calendar_id: str = "primary",
) -> list[dict]:
    """List events in [time_min, time_max) (RFC3339 strings), expanding
    recurring events (singleEvents) and ordered by start time. Returns
    normalized event dicts."""
    params = {
        "timeMin": time_min,
        "timeMax": time_max,
        "singleEvents": "true",
        "orderBy": "startTime",
        "maxResults": str(max_results),
    }
    try:
        resp = httpx.get(
            f"{_CALENDAR_API}/calendars/{calendar_id}/events",
            params=params,
            headers=_auth_headers(user_id),
            timeout=20.0,
        )
    except httpx.HTTPError as e:
        raise GoogleCalendarError(f"events.list unreachable: {e}") from e
    if resp.status_code >= 400:
        raise GoogleCalendarError(f"events.list {resp.status_code}: {resp.text[:300]}")
    return [_normalize_event(e) for e in resp.json().get("items", [])]


def get_event(user_id: str, event_id: str, *, calendar_id: str = "primary") -> dict:
    """Fetch a single event by id; returns the normalized projection."""
    try:
        resp = httpx.get(
            f"{_CALENDAR_API}/calendars/{calendar_id}/events/{event_id}",
            headers=_auth_headers(user_id),
            timeout=20.0,
        )
    except httpx.HTTPError as e:
        raise GoogleCalendarError(f"events.get unreachable: {e}") from e
    if resp.status_code == 404:
        raise GoogleCalendarError("event not found")
    if resp.status_code >= 400:
        raise GoogleCalendarError(f"events.get {resp.status_code}: {resp.text[:300]}")
    return _normalize_event(resp.json())


def create_event(
    user_id: str,
    *,
    title: str,
    start: str,
    end: str,
    attendees: Optional[list[str]] = None,
    description: str = "",
    add_meet: bool = True,
    calendar_id: str = "primary",
) -> dict:
    """Create an event, optionally provisioning a Google Meet link.

    `start`/`end` are RFC3339 datetimes. When `add_meet` is set we attach a
    conferenceData.createRequest so Google mints a fresh Meet link (requires
    conferenceDataVersion=1). Returns the normalized created event."""
    body: dict = {
        "summary": title,
        "description": description,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]
    params = {}
    if add_meet:
        # The createRequest.requestId must be unique per request; a random
        # token is fine (idempotency isn't a concern for a user-initiated
        # create).
        body["conferenceData"] = {
            "createRequest": {
                "requestId": secrets.token_hex(8),
                "conferenceSolutionKey": {"type": "hangoutsMeet"},
            }
        }
        params["conferenceDataVersion"] = "1"
    try:
        resp = httpx.post(
            f"{_CALENDAR_API}/calendars/{calendar_id}/events",
            params=params,
            json=body,
            headers={**_auth_headers(user_id), "Content-Type": "application/json"},
            timeout=20.0,
        )
    except httpx.HTTPError as e:
        raise GoogleCalendarError(f"events.insert unreachable: {e}") from e
    if resp.status_code >= 400:
        raise GoogleCalendarError(f"events.insert {resp.status_code}: {resp.text[:300]}")
    return _normalize_event(resp.json())
