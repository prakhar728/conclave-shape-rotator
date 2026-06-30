"""In-app user feedback (Task #19).

`POST /api/feedback`  (session-authed)

One row per submission from the `/feedback` page → `feedback` table (Alembic
0021), then a **best-effort** team email (reuses `infra/email.py` Resend, which
stub-logs when no key is set). The email is fire-and-forget: a failed or
unconfigured notify NEVER fails the submit — the row is the source of truth.

Submitter email + id are stamped server-side from the session (not trusted from
the client). Devs query the table directly for v1 (no in-app triage view yet —
see TASK-19 §8).
"""
from __future__ import annotations

import logging
from typing import Optional

from typing import List

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, field_validator

from auth.session import require_admin, require_current_user
from config import settings
from infra import email as email_mod
from infra import feedback as feedback_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/feedback", tags=["feedback"])


class FeedbackBody(BaseModel):
    category: str
    body: str
    page_context: Optional[str] = None
    workspace_id: Optional[str] = None

    @field_validator("category")
    @classmethod
    def _category_allowed(cls, v: str) -> str:
        if v not in feedback_store.CATEGORIES:
            raise ValueError(
                f"category must be one of {feedback_store.CATEGORIES}"
            )
        return v

    @field_validator("body")
    @classmethod
    def _body_nonempty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("body is required")
        return v.strip()


class FeedbackResponse(BaseModel):
    id: str
    created_at: str


class FeedbackItem(BaseModel):
    id: str
    user_id: Optional[str] = None
    user_email: str
    workspace_id: Optional[str] = None
    category: str
    body: str
    page_context: Optional[str] = None
    created_at: str


class FeedbackListResponse(BaseModel):
    items: List[FeedbackItem]
    total: int
    limit: int
    offset: int


def _notify_team(row: dict) -> None:
    """Best-effort team email on submit. Never raises — a notify failure must
    not turn a successful insert into a 500."""
    recipient = settings.feedback_notify_email
    if not recipient:
        return  # no team address configured → nothing to send (still wrote the row)
    try:
        email_mod.send_feedback_notification(
            recipient_email=recipient,
            category=row["category"],
            body=row["body"],
            submitter_email=row["user_email"],
            page_context=row.get("page_context"),
        )
    except Exception:  # noqa: BLE001 — notify is fire-and-forget; submit already succeeded
        logger.warning("feedback notify failed for %s", row["id"], exc_info=True)


@router.post("", response_model=FeedbackResponse)
def submit_feedback(
    body: FeedbackBody,
    user: dict = Depends(require_current_user),
) -> FeedbackResponse:
    row = feedback_store.record_feedback(
        user_id=user["id"],
        user_email=user["email"],
        category=body.category,
        body=body.body,
        page_context=body.page_context,
        workspace_id=body.workspace_id,
    )
    _notify_team(row)
    return FeedbackResponse(id=row["id"], created_at=row["created_at"])


@router.get("", response_model=FeedbackListResponse)
def list_feedback(
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    _admin: dict = Depends(require_admin),
) -> FeedbackListResponse:
    """Admin-only inbox: newest-first page of submitted feedback.

    Gated by `require_admin` (CONCLAVE_ADMIN_EMAILS, checked in-enclave) — this is
    the operator-blind read path: the enclave serves its own table to an
    authenticated admin over HTTPS instead of exposing a DB shell.
    """
    items = feedback_store.list_feedback(limit=limit, offset=offset)
    return FeedbackListResponse(
        items=[FeedbackItem(**it) for it in items],
        total=feedback_store.count_feedback(),
        limit=limit,
        offset=offset,
    )
