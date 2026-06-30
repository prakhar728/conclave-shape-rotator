"""Feedback inbox storage (Task #19).

Thin insert/read over the `feedback` table (Alembic 0021). One row per in-app
submission from the `/feedback` page. The table is append-only and FK-free — devs
query it directly for v1 (no in-app triage view yet).
"""
from __future__ import annotations

import uuid
from typing import Optional

from storage.sqlite import _get_conn, _now

# Allowed categories — kept here so the route, the model, and any future admin
# view share one source of truth.
CATEGORIES = ("feature", "bug", "other")


def record_feedback(
    *,
    user_id: Optional[str],
    user_email: str,
    category: str,
    body: str,
    page_context: Optional[str] = None,
    workspace_id: Optional[str] = None,
) -> dict:
    """Insert one feedback row and return it as a dict. Stamps id + created_at."""
    feedback_id = uuid.uuid4().hex
    created_at = _now()
    _get_conn().execute(
        "INSERT INTO feedback "
        "(id, user_id, user_email, workspace_id, category, body, page_context, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            feedback_id,
            user_id,
            user_email,
            workspace_id,
            category,
            body,
            page_context,
            created_at,
        ),
    )
    return {
        "id": feedback_id,
        "user_id": user_id,
        "user_email": user_email,
        "workspace_id": workspace_id,
        "category": category,
        "body": body,
        "page_context": page_context,
        "created_at": created_at,
    }


_COLUMNS = (
    "id, user_id, user_email, workspace_id, category, body, page_context, created_at"
)


def list_feedback(*, limit: int = 100, offset: int = 0) -> list:
    """Newest-first page of feedback rows (admin read surface). Returns dicts."""
    rows = _get_conn().execute(
        f"SELECT {_COLUMNS} FROM feedback "
        "ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [dict(r) for r in rows]


def count_feedback() -> int:
    """Total feedback rows (for the admin list's pagination/total)."""
    row = _get_conn().execute("SELECT COUNT(*) AS n FROM feedback").fetchone()
    return int(row["n"]) if row else 0
