"""Workspace type: personal vs team (Task #25).

Adds `workspaces.type` — 'personal' (auto-provisioned on first login, solo,
NON-invitable) vs 'team' (explicitly created, invite-gated). This replaces the
strict link-only / seeded `demo-ws` model: every authenticated user now
auto-gets a `Personal` workspace instead of a 403, and collaboration happens in
`team` workspaces you create + invite people into.

Backfill: auto-provisioned personal workspaces were named "Personal", so those
become type='personal'; everything else defaults to 'team' (invitable), which is
the safe default for the non-invitable gate.

Revision ID: 0028_workspace_type
Revises: 0027_workspace_membership
Create Date: 2026-07-07
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0028_workspace_type"
down_revision = "0027_workspace_membership"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(
            sa.Column("type", sa.Text, nullable=False, server_default="team")
        )
    op.execute("UPDATE workspaces SET type = 'personal' WHERE name = 'Personal'")


def downgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("type")
