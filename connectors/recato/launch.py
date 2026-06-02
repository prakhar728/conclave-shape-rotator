"""Server-side helper to launch a Recato bot for a Google Meet.

Called from `api/bot_routes.py`. Conclave holds ONE shared Recato API
token (BUILD_DOC §4 D-shared-bot) so end-users never touch Recato; this
module is the only thing in the codebase that calls `POST /bots`.

Errors from Recato bubble up as `RecatoLaunchError` so the route handler
can return a clean 502.
"""
from __future__ import annotations

import os
import re
from typing import Optional
from urllib.parse import urlparse

import httpx

DEFAULT_BOT_NAME = "Conclave"


class RecatoLaunchError(Exception):
    """Recato API returned a non-2xx response or didn't reach. Detail in `.args[0]`."""


_MEET_CODE_RE = re.compile(r"^[a-z]{3}-[a-z]{4}-[a-z]{3}$", re.IGNORECASE)


def parse_meet_input(meet: str) -> str:
    """Accept either a full Google Meet URL or a bare meet code; return the code.

    Raises ValueError if neither shape matches.
    """
    meet = (meet or "").strip()
    if not meet:
        raise ValueError("Meet URL or code is required")

    if _MEET_CODE_RE.match(meet):
        return meet.lower()

    # Treat as URL — accept https://meet.google.com/abc-defg-hij or with a slash suffix.
    if "://" in meet:
        u = urlparse(meet)
        host = (u.hostname or "").lower()
        if host not in ("meet.google.com", "www.meet.google.com"):
            raise ValueError(f"Unsupported host: {host or '<empty>'}")
        # The path is /xxx-xxxx-xxx, possibly with a trailing slash or query.
        candidate = (u.path or "").strip("/").split("/")[0]
        if _MEET_CODE_RE.match(candidate):
            return candidate.lower()
        raise ValueError("Couldn't extract a Meet code from that URL")

    raise ValueError("Input must be a Google Meet URL or an abc-defg-hij code")


def launch_bot(
    *,
    platform: str = "google_meet",
    native_meeting_id: str,
    language: str = "en",
    bot_name: str = DEFAULT_BOT_NAME,
    webhook_url: Optional[str] = None,
    timeout_s: float = 30.0,
) -> dict:
    """POST /bots on Recato. Returns the JSON body (typically `{id, status, ...}`)."""
    base = (os.environ.get("RECATO_API_BASE_URL") or "").rstrip("/")
    token = os.environ.get("RECATO_API_TOKEN") or ""
    if not base or not token:
        raise RecatoLaunchError(
            "Recato is not configured (RECATO_API_BASE_URL / RECATO_API_TOKEN missing)"
        )

    payload: dict = {
        "platform": platform,
        "native_meeting_id": native_meeting_id,
        "language": language,
        "bot_name": bot_name,
    }

    headers = {
        "X-API-Key": token,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }
    if webhook_url:
        # Vexa/Recato reads per-meeting webhook config from request HEADERS,
        # not the body — see meeting-api/meeting_api/meetings.py around
        # `X-User-Webhook-URL`. Passing it on the body is silently ignored.
        # Verified via the Vexa source after a Phase 2.5 misfire where no
        # webhook ever fired despite the field being set.
        headers["X-User-Webhook-URL"] = webhook_url
        # Webhook secret (HMAC for the inbound side) can ride along too —
        # we use RECATO_WEBHOOK_SECRET on the receiver, so if we want HMAC
        # in dev we need to forward the same secret here.
        webhook_secret = os.environ.get("RECATO_WEBHOOK_SECRET")
        if webhook_secret:
            headers["X-User-Webhook-Secret"] = webhook_secret

    try:
        resp = httpx.post(
            f"{base}/bots",
            json=payload,
            headers=headers,
            timeout=timeout_s,
        )
    except httpx.HTTPError as e:
        raise RecatoLaunchError(f"Recato unreachable: {e}") from e

    if resp.status_code >= 400:
        raise RecatoLaunchError(
            f"Recato {resp.status_code}: {resp.text[:300]}"
        )
    try:
        return resp.json()
    except Exception as e:  # noqa: BLE001
        raise RecatoLaunchError(f"Recato response not JSON: {e}") from e


def stop_bot(
    *,
    platform: str = "google_meet",
    native_meeting_id: str,
    timeout_s: float = 30.0,
) -> dict:
    """DELETE the bot for a meeting. Recato/Vexa keys this by (platform,
    native_meeting_id) — not by the bot's internal id. Triggers Recato's
    own meeting-completed flow, so the webhook fires the same way it would
    if the user kicked the bot from Meet directly.

    Returns the JSON body (typically `{"status": "deleted"}` or similar).
    """
    base = (os.environ.get("RECATO_API_BASE_URL") or "").rstrip("/")
    token = os.environ.get("RECATO_API_TOKEN") or ""
    if not base or not token:
        raise RecatoLaunchError(
            "Recato is not configured (RECATO_API_BASE_URL / RECATO_API_TOKEN missing)"
        )
    try:
        resp = httpx.delete(
            f"{base}/bots/{platform}/{native_meeting_id}",
            headers={
                "X-API-Key": token,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=timeout_s,
        )
    except httpx.HTTPError as e:
        raise RecatoLaunchError(f"Recato unreachable: {e}") from e
    if resp.status_code >= 400:
        raise RecatoLaunchError(
            f"Recato {resp.status_code}: {resp.text[:300]}"
        )
    try:
        return resp.json() if resp.content else {"status": "deleted"}
    except Exception:  # noqa: BLE001
        return {"status": "deleted"}
