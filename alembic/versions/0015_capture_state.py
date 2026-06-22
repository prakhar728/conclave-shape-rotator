"""Capture-microservice state: per-workspace concurrency caps + assigned account.

Part of the P1 "Conclave drives capture" work (see CONCLAVE-CAPTURE-ARCHITECTURE.md).
Conclave now dispatches bots to the stateless `capture` microservice and enforces
concurrency itself, so:

- `workspaces.max_active_meetings` — per-workspace cap on concurrent live bots
  (the dispatcher counts active `bot_invitations` against this). Default 2.
- `workspaces.fpm_workspace_id` — maps a Conclave workspace to its FPM/VFTE identity
  scope (nullable; filled when identity wiring lands in P4).
- `bot_invitations.assigned_account_id` — which warmed Google account drove this bot.
  For now this holds the single shared account id; a real per-workspace pool is
  deferred to P6 (no `workspace_accounts` table yet).

All nullable / defaulted, so existing rows are untouched.

Revision ID: 0015_capture_state
Revises: 0014_bot_invitation_intent
Create Date: 2026-06-21
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_capture_state"
down_revision = "0014_bot_invitation_intent"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("workspaces") as batch:
        batch.add_column(
            sa.Column("max_active_meetings", sa.Integer, nullable=False, server_default="2")
        )
        batch.add_column(sa.Column("fpm_workspace_id", sa.Text, nullable=True))
    with op.batch_alter_table("bot_invitations") as batch:
        batch.add_column(sa.Column("assigned_account_id", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bot_invitations") as batch:
        batch.drop_column("assigned_account_id")
    with op.batch_alter_table("workspaces") as batch:
        batch.drop_column("fpm_workspace_id")
        batch.drop_column("max_active_meetings")
