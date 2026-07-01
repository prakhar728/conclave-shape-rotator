"""Account settings surface (Transcript Saving, Phase 2).

A small authenticated CRUD over `users.settings` (JSON). Today it carries one
preference — the account-wide transcript retention default — but the blob is
deliberately open so later prefs slot in without new endpoints.

`retention_days`:
  - null  → keep transcripts forever (the default)
  - int>0 → auto-delete each transcript's RAW text N days after it was created
            (summary + KB are always kept; see transcripts/retention.py)

Per-meeting overrides live on the meeting itself (api/bot_routes.py); this is
just the account-wide default they inherit from.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from auth.session import require_current_user
from infra import identity, tnc

router = APIRouter(prefix="/api/users", tags=["users"])


class SettingsResponse(BaseModel):
    retention_days: Optional[int] = None


class UpdateSettingsBody(BaseModel):
    # null = keep forever; a positive int = auto-delete raw after N days.
    retention_days: Optional[int] = None


@router.get("/me/settings", response_model=SettingsResponse)
def get_my_settings(user: dict = Depends(require_current_user)) -> SettingsResponse:
    return SettingsResponse(
        retention_days=identity.get_account_retention_days(user["id"])
    )


@router.post("/me/settings", response_model=SettingsResponse)
def update_my_settings(
    body: UpdateSettingsBody,
    user: dict = Depends(require_current_user),
) -> SettingsResponse:
    if body.retention_days is not None and body.retention_days <= 0:
        raise HTTPException(
            status_code=422,
            detail="retention_days must be a positive integer, or null for keep-forever",
        )
    settings = identity.get_user_settings(user["id"])
    settings["retention_days"] = body.retention_days
    identity.set_user_settings(user["id"], settings)
    return SettingsResponse(retention_days=body.retention_days)


# ---------------------------------------------------------------------------
# Terms & Conditions (Task #18) — the copy + a recorded-acceptance endpoint.
# The blocking first-login gate reads `needs_acceptance`; Settings mirrors the
# same `text`. Acceptance is stamped on `users` (tnc_accepted_at / tnc_version).
# ---------------------------------------------------------------------------


class TncResponse(BaseModel):
    version: str
    text: str
    accepted_at: Optional[str] = None
    accepted_version: Optional[str] = None
    needs_acceptance: bool


class AcceptTncBody(BaseModel):
    version: str


@router.get("/me/tnc", response_model=TncResponse)
def get_my_tnc(user: dict = Depends(require_current_user)) -> TncResponse:
    """Current terms copy + this user's acceptance state.

    `needs_acceptance` is True until the user has accepted the CURRENT version
    — a version bump re-fires it. The gate blocks the app on this flag.
    """
    status = identity.get_tnc_status(user["id"])
    return TncResponse(
        version=tnc.TNC_VERSION,
        text=tnc.TNC_TEXT,
        accepted_at=status["accepted_at"],
        accepted_version=status["version"],
        needs_acceptance=status["version"] != tnc.TNC_VERSION,
    )


@router.post("/me/tnc/accept", response_model=TncResponse)
def accept_my_tnc(
    body: AcceptTncBody,
    user: dict = Depends(require_current_user),
) -> TncResponse:
    """Record that the current user accepted the terms.

    Rejects a version that isn't the current one (422) so a stale client can't
    satisfy the gate against outdated terms — it must re-fetch and re-accept.
    """
    if body.version != tnc.TNC_VERSION:
        raise HTTPException(
            status_code=422,
            detail=f"unknown terms version {body.version!r}; current is {tnc.TNC_VERSION!r}",
        )
    status = identity.accept_tnc(user["id"], tnc.TNC_VERSION)
    return TncResponse(
        version=tnc.TNC_VERSION,
        text=tnc.TNC_TEXT,
        accepted_at=status["accepted_at"],
        accepted_version=status["version"],
        needs_acceptance=False,
    )
