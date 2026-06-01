"""Server-side auth sessions for cookie-based login.

Opaque tokens (not JWT) so logout = delete-row (real revocation in v1).
Token is the PK to keep lookups O(1) on every request.

Rolling refresh policy lives in `auth/session.py`, not in the schema —
the schema just tracks expires_at + last_seen_at so the helper can decide
when to extend.

Revision ID: 0003_sessions
Revises: 0002_workspace_data_model
Create Date: 2026-06-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_sessions"
down_revision = "0002_workspace_data_model"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sessions",
        sa.Column("token", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("expires_at", sa.Text, nullable=False),
        sa.Column("last_seen_at", sa.Text, nullable=False),
    )
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])
    op.create_index("ix_sessions_expires_at", "sessions", ["expires_at"])


def downgrade() -> None:
    op.drop_index("ix_sessions_expires_at", table_name="sessions")
    op.drop_index("ix_sessions_user_id", table_name="sessions")
    op.drop_table("sessions")
