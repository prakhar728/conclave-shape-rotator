"""Add a per-share `scope` to meeting_shares (summary-only vs full transcript).

Transcript Saving feature, Phase 1. Until now a `meeting_shares` row was a
binary grant: the recipient could see everything the owner could (minus the
raw transcript, which the API never served at all). This feature introduces a
gated raw-transcript surface, so a share now needs to say HOW MUCH it grants:

- 'summary_and_transcript' (default) → recipient may also load the raw
  transcript via GET /transcripts/sessions/{id}/transcript.
- 'summary_only'                      → recipient sees the summary/signals/
  entities but is denied the raw transcript.

Existing rows predate the column and back-fill to the default
('summary_and_transcript'), preserving today's "shared = full access"
behaviour for anyone already granted.

Revision ID: 0012_meeting_share_scope
Revises: 0011_google_calendar
Create Date: 2026-06-08

Re-chained from 0010 to 0011_google_calendar when feat/transcript-saving
merged feat/google-calendar-integration: both branches had originally added
an 0011 off 0010, so this side moved to 0012 to keep the chain linear.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_meeting_share_scope"
down_revision = "0011_google_calendar"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch_alter_table reconstructs the table on SQLite so the CHECK
    # constraint lands cleanly (same pattern as 0004's visibility column).
    with op.batch_alter_table("meeting_shares") as batch:
        batch.add_column(
            sa.Column(
                "scope",
                sa.Text,
                nullable=False,
                server_default="summary_and_transcript",
            )
        )
        batch.create_check_constraint(
            "ck_meeting_shares_scope",
            "scope IN ('summary_and_transcript','summary_only')",
        )


def downgrade() -> None:
    with op.batch_alter_table("meeting_shares") as batch:
        batch.drop_constraint("ck_meeting_shares_scope", type_="check")
        batch.drop_column("scope")
