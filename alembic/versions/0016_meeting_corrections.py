"""Per-user correction stats for ramp-up trust graduation (#3).

One row per (user, session): how many corrections the user made on that draft,
and when it was approved. The correction-rate over recent approved meetings drives
gated→auto graduation (transcripts/trust.py). Additive; FK cascades with the session.

Revision ID: 0016_meeting_corrections
Revises: 0015_transcript_v2_and_vocab
Create Date: 2026-06-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_meeting_corrections"
down_revision = "0015_transcript_v2_and_vocab"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "meeting_corrections",
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column(
            "session_id", sa.Text,
            sa.ForeignKey("transcript_sessions.session_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("correction_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("approved_at", sa.Text, nullable=True),  # NULL until finalized
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "session_id", name="pk_meeting_corrections"),
    )
    op.create_index("ix_meeting_corrections_user", "meeting_corrections", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_meeting_corrections_user", table_name="meeting_corrections")
    op.drop_table("meeting_corrections")
