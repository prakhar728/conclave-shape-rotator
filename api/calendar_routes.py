"""Google Calendar HTTP surface — OAuth connect + (later) events.

Mounted at `/api/calendar/*`. All routes 503 when the integration is
unconfigured (`settings.google_calendar_enabled()` is False), mirroring the
Supabase `_require_*` guard in `auth/routes.py`.

OAuth model: a *dedicated* Google consent flow (separate from Supabase
login) so we obtain Calendar scopes + offline access and hold a refresh
token for the background auto-dispatch poller.

Endpoints (this step):
- GET  /api/calendar/connect      → { auth_url }  (start consent)
- GET  /api/calendar/callback     → redirect back to the app after storing tokens
- GET  /api/calendar/status       → { connected, scopes?, connected_at? }
- POST /api/calendar/disconnect   → { ok: true }
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, EmailStr, Field

from auth.session import require_current_user
from config import settings
from infra import crypto, google_calendar as gc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/calendar", tags=["calendar"])


def _require_configured() -> None:
    if not settings.google_calendar_enabled():
        raise HTTPException(
            status_code=503,
            detail="Google Calendar integration is not configured "
            "(CONCLAVE_GOOGLE_CLIENT_ID / CLIENT_SECRET / REDIRECT_URI missing)",
        )
    if not crypto.available():
        raise HTTPException(
            status_code=503,
            detail="Token encryption key (CONCLAVE_TOKEN_ENC_KEY) is not set",
        )


def _post_connect_redirect() -> str:
    """Where to send the browser after the OAuth callback completes. Defaults
    to the dashboard; override via CONCLAVE_CALENDAR_POST_CONNECT_URL."""
    return os.environ.get("CONCLAVE_CALENDAR_POST_CONNECT_URL", "/dashboard")


@router.get("/connect")
def connect(user: dict = Depends(require_current_user)):
    """Return the Google consent URL for the signed-in user to visit."""
    _require_configured()
    state = gc.make_state(user["id"])
    return {"auth_url": gc.build_auth_url(state)}


@router.get("/callback")
def callback(
    state: str = Query(...),
    code: str | None = Query(default=None),
    error: str | None = Query(default=None),
):
    """Google redirects here after consent.

    Public (no session dependency): the signed `state` carries + proves the
    user identity, so this works even if the session cookie didn't survive
    Google's cross-site redirect. On success we store encrypted tokens and
    bounce the browser back into the app.
    """
    _require_configured()

    if error:
        # User declined consent, or Google returned an error.
        return RedirectResponse(url=f"{_post_connect_redirect()}?calendar=denied", status_code=302)
    if not code:
        raise HTTPException(status_code=400, detail="missing authorization code")

    try:
        user_id = gc.verify_state(state)
    except gc.GoogleOAuthError as e:
        raise HTTPException(status_code=400, detail=f"invalid state: {e}")

    try:
        tokens = gc.exchange_code(code)
    except gc.GoogleOAuthError as e:
        raise HTTPException(status_code=502, detail=str(e))

    gc.save_tokens(
        user_id=user_id,
        access_token=tokens.get("access_token"),
        refresh_token=tokens.get("refresh_token"),
        expiry=tokens.get("expiry"),
        scopes=tokens.get("scope", " ".join(gc.SCOPES)),
    )
    logger.info("calendar: stored Google tokens for user %s", user_id)
    return RedirectResponse(url=f"{_post_connect_redirect()}?calendar=connected", status_code=302)


@router.get("/status")
def status(user: dict = Depends(require_current_user)):
    """Whether the signed-in user has connected Google Calendar."""
    _require_configured()
    tokens = gc.get_tokens(user["id"]) if gc.is_connected(user["id"]) else None
    if tokens is None:
        return {"connected": False}
    return {
        "connected": True,
        "scopes": tokens["scopes"],
        "connected_at": tokens["connected_at"],
    }


@router.post("/disconnect")
def disconnect(user: dict = Depends(require_current_user)):
    """Forget the user's stored Google tokens. Idempotent."""
    _require_configured()
    gc.delete_tokens(user["id"])
    return {"ok": True}


def _require_connected(user_id: str) -> None:
    if not gc.is_connected(user_id):
        raise HTTPException(status_code=409, detail="Google Calendar not connected")


@router.get("/events")
def list_events(
    user: dict = Depends(require_current_user),
    window_hours: int = Query(default=168, ge=1, le=744),  # default 7 days, max 31
):
    """List the signed-in user's upcoming events over the next `window_hours`.

    Annotates each event with `auto_record` (whether the auto-dispatch poller
    will send the bot to it)."""
    _require_configured()
    _require_connected(user["id"])
    now = datetime.now(timezone.utc)
    try:
        events = gc.list_events(
            user["id"],
            time_min=now.isoformat(),
            time_max=(now + timedelta(hours=window_hours)).isoformat(),
        )
    except gc.GoogleOAuthError as e:
        raise HTTPException(status_code=409, detail=f"reconnect required: {e}")
    except gc.GoogleCalendarError as e:
        raise HTTPException(status_code=502, detail=str(e))

    # Annotate with auto-record opt-in state.
    from infra import calendar_auto_record as car
    enabled_ids = car.enabled_event_ids(user["id"])
    for ev in events:
        ev["auto_record"] = ev["id"] in enabled_ids
    return {"events": events}


class CreateEventBody(BaseModel):
    title: str = Field(min_length=1)
    start: str = Field(min_length=1)  # RFC3339
    end: str = Field(min_length=1)
    attendees: Optional[List[EmailStr]] = None
    description: str = ""
    add_meet: bool = True


@router.post("/events", status_code=201)
def create_event(
    body: CreateEventBody,
    user: dict = Depends(require_current_user),
):
    """Create a calendar event (with a Meet link by default)."""
    _require_configured()
    _require_connected(user["id"])
    try:
        event = gc.create_event(
            user["id"],
            title=body.title,
            start=body.start,
            end=body.end,
            attendees=[str(e) for e in body.attendees] if body.attendees else None,
            description=body.description,
            add_meet=body.add_meet,
        )
    except gc.GoogleOAuthError as e:
        raise HTTPException(status_code=409, detail=f"reconnect required: {e}")
    except gc.GoogleCalendarError as e:
        raise HTTPException(status_code=502, detail=str(e))
    return {"event": event}


class AutoRecordBody(BaseModel):
    enabled: bool
    workspace_id: str = Field(min_length=1)


@router.post("/events/{event_id}/auto-record")
def set_auto_record(
    event_id: str,
    body: AutoRecordBody,
    user: dict = Depends(require_current_user),
):
    """Opt an event in/out of auto-recording.

    Enabling requires the event to have a Google Meet link (we fetch it
    server-side to capture the authoritative meet_code for the poller). The
    workspace must be one the user belongs to — that's where the recorded
    transcript will land."""
    _require_configured()
    _require_connected(user["id"])

    from infra import workspaces
    ws = workspaces.get_workspace(body.workspace_id)
    if ws is None or not workspaces.is_member(body.workspace_id, user["id"]):
        raise HTTPException(status_code=404, detail="Workspace not found")

    from infra import calendar_auto_record as car

    meet_code = None
    if body.enabled:
        try:
            event = gc.get_event(user["id"], event_id)
        except gc.GoogleOAuthError as e:
            raise HTTPException(status_code=409, detail=f"reconnect required: {e}")
        except gc.GoogleCalendarError as e:
            raise HTTPException(status_code=502, detail=str(e))
        meet_code = event.get("meet_code")
        if not meet_code:
            raise HTTPException(
                status_code=422,
                detail="event has no Google Meet link — can't auto-record",
            )

    car.set_auto_record(
        user_id=user["id"],
        google_event_id=event_id,
        workspace_id=body.workspace_id,
        meet_code=meet_code,
        enabled=body.enabled,
    )
    return {"ok": True, "event_id": event_id, "enabled": body.enabled, "meet_code": meet_code}
