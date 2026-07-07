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

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from auth.session import require_current_user
from infra import workspaces
from infra.meeting_lifecycle import meeting_lifecycle
from infra.meeting_origin import resolve_origin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/workspaces", tags=["workspaces"])


class CreateWorkspaceBody(BaseModel):
    name: str = Field(min_length=1, max_length=80)


def _require_member(workspace_id: str, user_id: str) -> dict:
    """Resolve workspace and assert membership. 404 if either fails."""
    ws = workspaces.get_workspace(workspace_id)
    if ws is None or not workspaces.is_member(workspace_id, user_id):
        raise HTTPException(status_code=404, detail="Workspace not found")
    return ws


def _require_owner(workspace_id: str, user_id: str) -> dict:
    """Resolve workspace + assert the caller is an OWNER (the manage gate, §0b-C).

    404 (not 403) when the caller isn't even a member, so a non-member can't probe
    which workspaces exist; 403 when they're a member but not an owner.
    """
    ws = _require_member(workspace_id, user_id)
    if not workspaces.is_owner(workspace_id, user_id):
        raise HTTPException(status_code=403, detail="Only the workspace owner can manage members")
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
    """List meetings in this workspace the caller can see, newest-first.

    Task #32 §0b-D: meetings are OWNER-PRIVATE by default — a member sees only the
    ones they own or that were explicitly shared to them (a per-recipient share OR a
    whole-workspace share). The `can_user_see` gate is the single source of truth for
    that decision (same one the detail endpoint enforces), so the list can't leak a
    meeting the detail view would 403.
    """
    _require_member(workspace_id, user["id"])
    from api.transcripts_routes import can_user_see
    from transcripts import store as _store
    sessions = _store.list_workspace_sessions(workspace_id)
    meetings = []
    for s in sessions:
        ws_fields = _store.get_workspace_fields(s.session_id)
        row = {"session_id": s.session_id, **ws_fields} if ws_fields else None
        if row is None or not can_user_see(user, row):
            continue
        summary = s.derived.summary if s.derived else None
        # Task #42 — a real lifecycle instead of `is_processing = not summary`
        # (which spun a "Sharpening insights…" card forever for cancelled/empty/
        # failed meetings). `processing` while enrich is in-flight and fresh;
        # `failed` once it errored or aged past the staleness cutoff; `done`
        # otherwise. `is_processing` stays as a bool for back-compat.
        lifecycle = meeting_lifecycle(
            s.metadata.enrichment_status, bool(summary), s.created_at,
        )
        meetings.append({
            "session_id": s.session_id,
            "date": s.metadata.date,
            # Task #39 — full ingest timestamp for time-of-day on the dashboard card.
            "created_at": s.created_at,
            "source": s.metadata.source,
            # Task #38 — origin badge (in_person / google_meet / upload / demo / …).
            "origin": resolve_origin(s),
            # Task #40 — short meeting title (owner rename wins over the auto title;
            # None → FE falls back to the summary first line).
            "title": s.metadata.manual_title or (s.derived.title if s.derived else None),
            "summary": summary,
            "is_processing": lifecycle == "processing",
            # Task #42 — the failed state drives the "couldn't generate insights"
            # card with Retry + Delete (no eternal spinner).
            "enrichment_state": lifecycle,
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


# ---------------------------------------------------------------------------
# Multi-membership (Task #32) — owner-only invite/list/remove + accept.
# ---------------------------------------------------------------------------


class InviteMemberBody(BaseModel):
    email: EmailStr
    role: str = "member"


@router.post("/{workspace_id}/members", status_code=201)
def add_workspace_member(
    workspace_id: str,
    body: InviteMemberBody,
    user: dict = Depends(require_current_user),
):
    """Owner invites an email to the workspace (Task #32).

    Creates a pending invite and emails an accept link. The recipient becomes a
    `workspace_members` row when they accept — either by clicking the link (an
    already-signed-in user) or automatically on their first sign-in (invites are
    hydrated by email, mirroring `meeting_shares`). Owner-only.
    """
    _require_owner(workspace_id, user["id"])
    if workspaces.is_personal(workspace_id):   # Task #25 — personal workspaces are solo
        raise HTTPException(
            status_code=403,
            detail="Personal workspaces are solo — create a team workspace to invite others.",
        )
    if body.role not in workspaces.WORKSPACE_ROLES:
        raise HTTPException(status_code=422,
                            detail=f"role must be one of {list(workspaces.WORKSPACE_ROLES)}")

    email = str(body.email).strip().lower()
    # Already a member? (the invited email resolves to an existing member) → 409.
    from infra import identity
    existing_user = identity.get_user_by_email(email)
    if existing_user and workspaces.is_member(workspace_id, existing_user["id"]):
        raise HTTPException(status_code=409, detail="That person is already a member")

    invite = workspaces.create_invite(
        workspace_id, email, role=body.role, invited_by=user["id"],
    )

    # Best-effort email — a send failure must not lose the invite (the recipient can
    # still be auto-added on signup, and the owner can re-send).
    try:
        from infra import email as _email
        from infra.magic_links import base_url
        _email.send_workspace_invite(
            recipient_email=email,
            accept_url=f"{base_url()}/invite/{invite['token']}",
            workspace_name=_require_member(workspace_id, user["id"]).get("name"),
            inviter_email=user.get("email"),
        )
    except Exception:  # noqa: BLE001 — never block the invite on an email hiccup
        logger.warning("workspace invite email to %s failed (invite still created)", email,
                       exc_info=True)

    return {"invite": {"id": invite["id"], "email": invite["email"],
                       "role": invite["role"], "created_at": invite["created_at"]}}


@router.get("/{workspace_id}/members")
def list_members(
    workspace_id: str,
    user: dict = Depends(require_current_user),
):
    """List current members + pending invites. Owner-only (membership is managed
    by the owner, §0b-C)."""
    _require_owner(workspace_id, user["id"])
    return {
        "members": workspaces.list_workspace_members(workspace_id),
        "invites": workspaces.list_pending_invites(workspace_id),
    }


@router.delete("/{workspace_id}/members/{member_user_id}")
def remove_member(
    workspace_id: str,
    member_user_id: str,
    user: dict = Depends(require_current_user),
):
    """Owner removes a member (revokes their workspace access). Owner-only.

    Refuses to remove the last owner (a workspace must always have one). Removing a
    member is content-side only — it does NOT touch VFTE voiceprint↔scope edges (#2).
    """
    _require_owner(workspace_id, user["id"])
    if member_user_id == user["id"] and workspaces.count_owners(workspace_id) <= 1:
        raise HTTPException(status_code=409, detail="Cannot remove the last owner")
    if workspaces.get_member_role(workspace_id, member_user_id) == "owner" and \
            workspaces.count_owners(workspace_id) <= 1:
        raise HTTPException(status_code=409, detail="Cannot remove the last owner")
    removed = workspaces.remove_workspace_member(workspace_id, member_user_id)
    if not removed:
        raise HTTPException(status_code=404, detail="Member not found")
    return {"ok": True, "removed": member_user_id}


class AcceptInviteBody(BaseModel):
    token: str


@router.post("/accept-invite")
def accept_invite(
    body: AcceptInviteBody,
    user: dict = Depends(require_current_user),
):
    """Accept a workspace invite by token → become a member (Task #32).

    Idempotent-ish: an unknown/already-consumed token 404s (the membership, if any,
    already exists). The email is not required to match the invite — clicking a valid
    link is the proof of intent (the token is unguessable), matching how meeting magic
    links work.
    """
    member = workspaces.accept_invite(body.token, user["id"])
    if member is None:
        raise HTTPException(status_code=404, detail="Invite not found or already used")
    ws = workspaces.get_workspace(member["workspace_id"])
    return {"workspace": ws, "role": member["role"]}
