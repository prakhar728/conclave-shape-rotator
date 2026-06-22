"""Server-side helper to launch a Recato bot for a Google Meet.

Called from `api/bot_routes.py`. Conclave holds ONE shared Recato API
token (BUILD_DOC §4 D-shared-bot) so end-users never touch Recato; this
module is the only thing in the codebase that calls `POST /bots`.

Errors from Recato bubble up as `RecatoLaunchError` so the route handler
can return a clean 502.
"""
from __future__ import annotations

import hashlib
import json
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
    api_token: Optional[str] = None,
    base_url: Optional[str] = None,
    user_id: Optional[str] = None,
    timeout_s: float = 30.0,
) -> dict:
    """POST /containers on the capture runtime-api. Returns the JSON body (a
    ContainerResponse: `{name, container_id, status, ...}` — note: no `id`).

    `api_token`/`base_url` (the per-workspace capture credentials) are preferred over the
    legacy shared `RECATO_API_*` env vars when supplied by the dispatcher (P1). `user_id`
    is the tenant/account the dispatcher assigned (runtime-api requires it)."""
    base = (base_url or os.environ.get("RECATO_API_BASE_URL") or "").rstrip("/")
    token = api_token or os.environ.get("RECATO_API_TOKEN") or ""
    if not base or not token:
        raise RecatoLaunchError(
            "Recato is not configured (RECATO_API_BASE_URL / RECATO_API_TOKEN missing)"
        )

    # The bot reads its ENTIRE meeting config from one env var, BOT_CONFIG, which the
    # capture runtime-api injects into the spawned container via config.env (capture
    # recato-bot core/src/docker.ts:71 parses process.env.BOT_CONFIG).
    meeting_url = (
        f"https://meet.google.com/{native_meeting_id}"
        if platform == "google_meet"
        else None
    )
    # `meeting_id` is a REQUIRED int the old Recato meeting-api supplied from its DB
    # PK. There is no meeting-api DB in the capture rebuild → synthesize a stable
    # 32-bit int from the meet code (the bot only needs uniqueness). ⚠️ run-pass unverified.
    synth_meeting_id = int(hashlib.sha256(native_meeting_id.encode()).hexdigest()[:8], 16)
    bot_config: dict = {
        "platform": platform,                       # google_meet | zoom | teams
        "meetingUrl": meeting_url,
        "botName": bot_name,
        "nativeMeetingId": native_meeting_id,
        "connectionId": native_meeting_id,
        "meeting_id": synth_meeting_id,
        "token": token,                             # was an HS256 MeetingToken from meeting-api; reuse the API token (⚠️ bot may not need it)
        "language": language,
        "redisUrl": os.environ.get("REDIS_URL", "redis://redis:6379/0"),
        "automaticLeave": {
            "waitingRoomTimeout": 300000,
            "noOneJoinedTimeout": 600000,
            "everyoneLeftTimeout": 120000,
        },
    }
    # Audio sink → Conclave's /api/capture/audio-chunk (post-meeting diarize+identify).
    audio_url = os.environ.get("CONCLAVE_AUDIO_INGEST_URL")
    if audio_url:
        bot_config["recordingUploadUrl"] = audio_url
    # Bot status-change callback (joining/active/left) → Conclave.
    status_cb = os.environ.get("CONCLAVE_CALLBACK_URL")
    if status_cb:
        bot_config["meetingApiCallbackUrl"] = status_cb

    # runtime-api CreateContainerRequest (capture services/runtime-api/.../api.py:39).
    # The bot config rides inside config.env.BOT_CONFIG; `user_id` is REQUIRED (the
    # tenant/account the dispatcher assigned). `callback_url` receives runtime-api's
    # container-lifecycle events (container exit ≈ meeting end → finalize webhook).
    payload: dict = {
        "profile": "meeting",
        "user_id": user_id or native_meeting_id,
        "name": f"bot-{native_meeting_id}",
        "config": {"env": {"BOT_CONFIG": json.dumps(bot_config)}},
    }
    if webhook_url:
        payload["callback_url"] = webhook_url

    # NOTE (capture rebuild): the OLD contract was `POST /bots` with a FLAT body
    # ({platform, native_meeting_id, language, bot_name, authenticated, userdataS3Path,
    # recordingEnabled, ...}) + a per-meeting webhook via the `X-User-Webhook-URL`
    # HEADER. That is replaced by the runtime-api `/containers` contract above. Warmed-
    # account auth is no longer a body flag + an in-container SingletonLock `docker exec`
    # against `recato-lite`; it now comes from the BOT_PROFILE_DIR bind mount the
    # `meeting` profile declares (capture .../profiles.yaml). ⚠️ the persistent-context
    # trigger for that mounted profile is UNVERIFIED — confirm at the run pass.

    headers = {
        "X-API-Key": token,
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    }

    try:
        resp = httpx.post(
            f"{base}/containers",
            json=payload,
            headers=headers,
            timeout=timeout_s,
        )
    except httpx.HTTPError as e:
        raise RecatoLaunchError(f"capture runtime-api unreachable: {e}") from e

    if resp.status_code >= 400:
        raise RecatoLaunchError(
            f"capture runtime-api {resp.status_code}: {resp.text[:300]}"
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
    """Stop the bot for a meeting via the capture runtime-api: DELETE
    /containers/{name}, where launch_bot named the container `bot-{native_meeting_id}`.

    (The old Recato contract was DELETE /bots/{platform}/{id}, keyed by platform +
    native id. runtime-api keys by container name.) `platform` is kept for signature
    compatibility but is unused now — the container name carries the meeting identity.

    Returns the JSON body (typically `{"status": "deleted"}` or similar).
    """
    base = (os.environ.get("RECATO_API_BASE_URL") or "").rstrip("/")
    token = os.environ.get("RECATO_API_TOKEN") or ""
    if not base or not token:
        raise RecatoLaunchError(
            "capture runtime-api is not configured (RECATO_API_BASE_URL / RECATO_API_TOKEN missing)"
        )
    name = f"bot-{native_meeting_id}"
    try:
        resp = httpx.delete(
            f"{base}/containers/{name}",
            headers={
                "X-API-Key": token,
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            timeout=timeout_s,
        )
    except httpx.HTTPError as e:
        raise RecatoLaunchError(f"capture runtime-api unreachable: {e}") from e
    if resp.status_code >= 400:
        raise RecatoLaunchError(
            f"capture runtime-api {resp.status_code}: {resp.text[:300]}"
        )
    try:
        return resp.json() if resp.content else {"status": "deleted"}
    except Exception:  # noqa: BLE001
        return {"status": "deleted"}
