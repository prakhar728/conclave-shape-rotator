"""Backfill: in-person recordings owned by their RECORDER, not the workspace creator.

The finalize webhook now stamps ``owner_user_id = recorder_user_id`` for in-person (walk-up)
meetings, so every owner-gated feature (share / editor / retention / delete / rename) works for the
person who actually recorded it. Existing ``capture`` sessions were bound to the workspace CREATOR —
re-point them to the recorder where one was stamped.

Idempotent + safe: only rewrites rows that have a recorder and whose owner differs from it.

Revision ID: 0029_inperson_recorder_owner
Revises: 0028_workspace_type
Create Date: 2026-07-07
"""
from __future__ import annotations

from alembic import op

revision = "0029_inperson_recorder_owner"
down_revision = "0028_workspace_type"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # SQLite `IS NOT` is NULL-safe inequality (≡ SQL `IS DISTINCT FROM`).
    op.execute(
        "UPDATE transcript_sessions "
        "SET owner_user_id = recorder_user_id "
        "WHERE source = 'capture' "
        "  AND recorder_user_id IS NOT NULL "
        "  AND owner_user_id IS NOT recorder_user_id"
    )


def downgrade() -> None:
    # No-op: the prior workspace-creator owner isn't retained, so it can't be restored. The forward
    # direction is idempotent, so re-running upgrade() is safe.
    pass
