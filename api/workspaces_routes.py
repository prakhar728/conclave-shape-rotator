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
    """List meetings in this workspace, newest-first.

    Phase 1.6 wired this to the typed `workspace_id` column. Phase 1.7
    layers the per-meeting visibility check on top — for now membership
    in the workspace is the only gate, so a member sees everything.
    """
    _require_member(workspace_id, user["id"])
    from transcripts import store as _store
    sessions = _store.list_workspace_sessions(workspace_id)
    meetings = []
    for s in sessions:
        summary = s.derived.summary if s.derived else None
        # A session is "processing" when it's been ingested but enrichment
        # hasn't filled in the summary yet. The window is ~30s-2min between
        # webhook arrival and LLM completion. Lets the frontend render a
        # placeholder card with progress copy instead of an empty one.
        is_processing = not summary
        meetings.append({
            "session_id": s.session_id,
            "date": s.metadata.date,
            "source": s.metadata.source,
            "summary": summary,
            "is_processing": is_processing,
        })
    return {"meetings": meetings}


@router.get("/{workspace_id}/open-questions")
def list_open_questions(
    workspace_id: str,
    user: dict = Depends(require_current_user),
):
    """Phase 3 — Open Questions Board (BUILD_DOC §4 D-3b).

    Aggregates every `open_question` signal across the workspace's
    sessions that the caller can see. Flat list, newest meeting first.
    Per-session visibility is enforced via `can_user_see` so a workspace
    member doesn't see questions from `owner-only` sessions they don't
    own.

    Schema decision (3.1): signals stay in the JSON `derived` column;
    we aggregate in Python at query time. N is small enough through v1
    that the loop is cheap. When (c)/(a) need fan-out queries at scale,
    promote `signals` to a typed table — until then JSON is the source
    of truth.
    """
    _require_member(workspace_id, user["id"])

    from api.transcripts_routes import can_user_see
    from transcripts import store as _store

    sessions = _store.list_workspace_sessions(workspace_id)
    visible_rows: list[dict] = []
    for s in sessions:
        row_fields = _store.get_workspace_fields(s.session_id)
        row = (
            {"session_id": s.session_id, **row_fields}
            if row_fields and row_fields.get("workspace_id")
            else None
        )
        if row is None:
            # Defensive — workspace-scoped fetch returned a session whose
            # workspace columns aren't populated. Skip rather than leak.
            continue
        if not can_user_see(user, row):
            continue
        visible_rows.append((s, row))

    questions: list[dict] = []
    for session, _row in visible_rows:
        signals = (session.derived.signals if session.derived else None) or []
        for sig in signals:
            if sig.kind != "open_question":
                continue
            questions.append(
                {
                    "text": sig.text,
                    "said_by": list(sig.said_by or []),
                    "source_quote": sig.source_quote,
                    "meeting": {
                        "session_id": session.session_id,
                        "date": session.metadata.date,
                        "source": session.metadata.source,
                        "summary": (
                            session.derived.summary if session.derived else None
                        ),
                    },
                }
            )

    # Newest first: session_date desc, then by source_id as a stable tiebreaker.
    questions.sort(
        key=lambda q: (q["meeting"]["date"], q["meeting"]["session_id"]),
        reverse=True,
    )
    return {"questions": questions}


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
