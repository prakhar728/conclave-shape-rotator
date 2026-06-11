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
from infra import identity

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
