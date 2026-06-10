"""Retention / auto-delete columns (Transcript Saving, Phase 2).

Auto-delete removes ONLY the raw transcript and keeps the summary + derived
KB, so retention is expressed as three small additions:

- users.settings (JSON)                         — account-wide preferences.
  Currently `{"retention_days": null | int}`; null = keep transcripts forever
  (the default). A JSON blob so later prefs don't each need a migration.
- transcript_sessions.retention_override (TEXT) — per-meeting override:
    NULL          → inherit the owner's account default
    'keep_forever'→ never auto-delete this one
    '<int>'       → delete this one's raw transcript after N days
- transcript_sessions.raw_transcript_deleted_at — set when the sweep purges
  the raw transcript. The presence of this timestamp is what the API turns
  into a 410 ("auto-deleted") on the transcript endpoint; the summary stays.

All columns are nullable / JSON, so existing rows are untouched (NULL ⇒ keep
forever ⇒ today's behaviour).

Revision ID: 0012_retention
Revises: 0011_meeting_share_scope
Create Date: 2026-06-08
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_retention"
down_revision = "0011_meeting_share_scope"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("settings", sa.Text, nullable=True))
    with op.batch_alter_table("transcript_sessions") as batch:
        batch.add_column(
            sa.Column("retention_override", sa.Text, nullable=True)
        )
        batch.add_column(
            sa.Column("raw_transcript_deleted_at", sa.Text, nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("transcript_sessions") as batch:
        batch.drop_column("raw_transcript_deleted_at")
        batch.drop_column("retention_override")
    with op.batch_alter_table("users") as batch:
        batch.drop_column("settings")
