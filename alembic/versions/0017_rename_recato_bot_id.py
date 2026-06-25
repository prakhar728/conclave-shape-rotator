"""Rename bot_invitations.recato_bot_id → capture_bot_id.

Part of the recato→capture rename: the capture microservice (the extracted
Recato bot) is the canonical capture engine, so the column that stores the
launched bot's id from the capture runtime-api is renamed to match. Pure
column rename — data is preserved (SQLite RENAME COLUMN, ≥3.25).

Revision ID: 0017_rename_recato_bot_id
Revises: 0016_live_segments
Create Date: 2026-06-25
"""
from alembic import op

revision = "0017_rename_recato_bot_id"
down_revision = "0016_live_segments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE bot_invitations RENAME COLUMN recato_bot_id TO capture_bot_id")


def downgrade() -> None:
    op.execute("ALTER TABLE bot_invitations RENAME COLUMN capture_bot_id TO recato_bot_id")
