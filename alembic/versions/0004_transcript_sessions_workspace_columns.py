"""Extend transcript_sessions with workspace_id / owner_user_id / visibility.

First Alembic migration to touch a legacy-owned table (still created by
storage.sqlite._init_schema). Subsequent saves go through the same JSON
metadata column AND these typed columns — typed columns become the
source of truth for can_see in Phase 1.7.

Existing 13 historical fixture rows survive untouched:
- workspace_id  → NULL (left out of any workspace's view in 1.7)
- owner_user_id → NULL
- visibility    → 'owner-only' (the table default)

FK references to workspaces(id) / users(id) work cleanly because those
tables already exist (Alembic 0002).

Revision ID: 0004_transcript_sessions_workspace_columns
Revises: 0003_sessions
Create Date: 2026-06-01
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_transcript_sessions_workspace_columns"
down_revision = "0003_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite batch mode is enabled in env.py — this becomes a proper rebuild
    # under the hood, picking up the CHECK constraint on visibility.
    # batch_alter_table reconstructs the table on SQLite; named constraints
    # are required so the rebuild doesn't trip alembic's validator.
    with op.batch_alter_table("transcript_sessions") as batch:
        batch.add_column(
            sa.Column(
                "workspace_id",
                sa.Text,
                sa.ForeignKey(
                    "workspaces.id", name="fk_transcript_sessions_workspace_id"
                ),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "owner_user_id",
                sa.Text,
                sa.ForeignKey(
                    "users.id", name="fk_transcript_sessions_owner_user_id"
                ),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column(
                "visibility",
                sa.Text,
                nullable=False,
                server_default="owner-only",
            )
        )
        batch.create_check_constraint(
            "ck_transcript_sessions_visibility",
            "visibility IN ('owner-only','shared','workspace','public-link')",
        )
    op.create_index(
        "ix_transcript_sessions_workspace_id",
        "transcript_sessions",
        ["workspace_id"],
    )
    op.create_index(
        "ix_transcript_sessions_owner_user_id",
        "transcript_sessions",
        ["owner_user_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transcript_sessions_owner_user_id", table_name="transcript_sessions"
    )
    op.drop_index(
        "ix_transcript_sessions_workspace_id", table_name="transcript_sessions"
    )
    with op.batch_alter_table("transcript_sessions") as batch:
        batch.drop_constraint("ck_transcript_sessions_visibility", type_="check")
        batch.drop_column("visibility")
        batch.drop_column("owner_user_id")
        batch.drop_column("workspace_id")
