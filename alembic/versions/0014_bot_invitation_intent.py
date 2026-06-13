"""Per-meeting intent on bot invitations.

Adds `bot_invitations.intent` (TEXT, nullable) — the optional freeform "focus /
what to capture" a user supplies when inviting the bot to a meeting that has no
calendar event. It's the only durable carrier from invite time to webhook-ingest
time, so it lives on the invitation row; at ingest it's copied onto
`SessionMetadata.raw_intent` and compiled into enrichment grounding
(transcripts/compile_intent.py). Nullable, so existing rows are untouched.

Revision ID: 0014_bot_invitation_intent
Revises: 0013_retention
Create Date: 2026-06-13
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_bot_invitation_intent"
down_revision = "0013_retention"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("bot_invitations") as batch:
        batch.add_column(sa.Column("intent", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("bot_invitations") as batch:
        batch.drop_column("intent")
