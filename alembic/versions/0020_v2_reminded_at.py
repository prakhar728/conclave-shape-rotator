"""Track the one-time post-meeting review reminder on the v2 draft (#9d).

`transcript_v2.reminded_at` — NULL until the review-reminder email is sent, so the
reminder sweep fires exactly once per draft. Not in the TranscriptV2 model (column
only) → the Part1→Part2 contract is unchanged.

Revision ID: 0017_v2_reminded_at
Revises: 0016_meeting_corrections
Create Date: 2026-06-22
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_v2_reminded_at"
down_revision = "0019_meeting_corrections"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("transcript_v2") as batch:
        batch.add_column(sa.Column("reminded_at", sa.Text, nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("transcript_v2") as batch:
        batch.drop_column("reminded_at")
