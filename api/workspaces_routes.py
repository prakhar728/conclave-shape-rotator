"""Workspace HTTP surface — list, create, details, meetings.

All routes require an authenticated user via `auth.session.require_current_user`.
v1 semantics (BUILD_DOC §11):
- Workspaces are single-member (the creator is the lone owner). The
  POST /members endpoint stubs out with a 501 to keep the contract
  visible without enabling multi-member behavior in v1.

The meetings list is workspace-scoped via `transcript_sessions.workspace_id`,
which lands in Phase 1.6. Until then the endpoint returns an empty list
with an explanatory note in the response — keeps the frontend wireable
without forcing a phase-ordering dependency.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth.session import require_current_user
from infra import workspaces

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class CreateWorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _require_member(workspace_id: str, user_id: str) -> dict:
    """Resolve workspace and assert membership. 404 if either fails."""
    ws = workspaces.get_workspace(workspace_id)
    if ws is None or not workspaces.is_member(workspace_id, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


@router.get("")
def list_workspaces(user: dict = Depends(require_current_user)):
    """List workspaces the current user is a member of."""
    return {"workspaces": workspaces.list_user_workspaces(user["id"])}


@router.post("", status_code=201)
def create_workspace(
    body: CreateWorkspaceBody,
    user: dict = Depends(require_current_user),
):
    """Create a workspace; the creator is added as 'owner'."""
    ws = workspaces.create_workspace(body.name.strip(), user["id"])
    return {"workspace": ws}


@router.get("/{workspace_id}")
def get_workspace(
    workspace_id: str,
    user: dict = Depends(require_current_user),
):
    ws = _require_member(workspace_id, user["id"])
    return {
        "workspace": ws,
        "role": workspaces.get_member_role(workspace_id, user["id"]),
    }


@router.get("/{workspace_id}/meetings")
def list_workspace_meetings(
    workspace_id: str,
    user: dict = Depends(require_current_user),
):
    """List meetings in this workspace.

    Returns [] until Phase 1.6 adds `transcript_sessions.workspace_id` and
    1.7 enforces workspace-scoped visibility. Wiring this endpoint now lets
    the frontend integrate against the final contract.
    """
    _require_member(workspace_id, user["id"])
    # TODO(1.6): query transcript_sessions WHERE workspace_id = ? AND visibility check.
    return {"meetings": [], "note": "Workspace-scoped meetings activate in Phase 1.6."}


@router.post("/{workspace_id}/members", status_code=501)
def add_workspace_member(
    workspace_id: str,
    user: dict = Depends(require_current_user),
):
    """Multi-member workspaces ship in v1.5 (BUILD_DOC §11)."""
    _require_member(workspace_id, user["id"])
    raise HTTPException(
        status_code=501,
        detail="Multi-member workspaces are not in v1. See BUILD_DOC §11.",
    )
