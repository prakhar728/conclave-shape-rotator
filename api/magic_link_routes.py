"""Magic-link HTTP surface for the recipient-side flow (Phase 2.10).

The link in the email is `${BASE_URL}/m/${token}` — Next.js renders that;
the frontend then calls this endpoint to resolve the token to a meeting.

Public (no auth required) so unauthenticated recipients can see what
they're being asked to sign in for. We DON'T return any transcript
content — just the meeting id + the recipient email (which the user
already knows; it's their inbox).
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from infra import magic_links

router = APIRouter(prefix="/api/magic-links", tags=["magic-links"])


@router.get("/{token}")
def lookup(token: str) -> dict:
    """Resolve a token to its bound meeting + recipient email. Public."""
    row = magic_links.resolve(token)
    if row is None:
        raise HTTPException(status_code=404, detail="Invalid or expired link")
    return {
        "meeting_session_id": row["meeting_session_id"],
        "user_email": row["user_email"],
        "consumed_at": row["consumed_at"],
    }


@router.post("/{token}/consume", status_code=200)
def consume_link(token: str) -> dict:
    """Mark the token consumed. Frontend calls this once the recipient lands
    on the meeting page successfully — keeps an audit trail of when the
    link was first opened (separate from when the row was created)."""
    row = magic_links.consume(token)
    if row is None:
        raise HTTPException(status_code=404, detail="Invalid or expired link")
    return {
        "meeting_session_id": row["meeting_session_id"],
        "user_email": row["user_email"],
        "consumed_at": row["consumed_at"],
    }
