"""User feedback inbox (Task #19).

A single append-only `feedback` table: one row per in-app submission from the
`/feedback` page. Captures who (denormalised submitter id + email, so the row
survives a future user delete), what (category + free-text body), and where the
user came from (`page_context` — the route/page they were on). Auto-stamped with
a UTC timestamp.

Deliberately FK-free (audit/inbox style, like FPM's `deletion_receipts`): we keep
feedback verbatim even if the user or workspace row is later removed, and it never
participates in the workspace-domain cascade. Devs query this table directly for v1
(no in-app triage view yet — see TASK-19 §8).

Revision ID: 0021_feedback
Revises: 0020_v2_reminded_at
Create Date: 2026-06-29
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_feedback"
down_revision = "0020_v2_reminded_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", sa.Text, primary_key=True),
        # Denormalised submitter — id + email so the row is self-describing even
        # if the user row is later deleted. Nullable id keeps it FK-free.
        sa.Column("user_id", sa.Text, nullable=True),
        sa.Column("user_email", sa.Text, nullable=False),
        # The workspace the user was in when they submitted (best-effort context).
        sa.Column("workspace_id", sa.Text, nullable=True),
        # 'feature' | 'bug' | 'other' (validated at the API boundary).
        sa.Column("category", sa.Text, nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        # The page/route the user came from (e.g. "/meeting/abc"). Optional.
        sa.Column("page_context", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_feedback_created_at", table_name="feedback")
    op.drop_table("feedback")
