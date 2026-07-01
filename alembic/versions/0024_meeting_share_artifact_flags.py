"""Replace the 2-value `scope` enum on meeting_shares with three independent
per-artifact boolean flags: share_transcript / share_insights / share_audio.

Task #31 — flexible sharing scopes. Until now a share was one of two levels:

- 'summary_and_transcript' → summary/signals/entities + raw transcript.
- 'summary_only'           → summary/signals/entities, transcript withheld.

Insights (summary/signals/entities) were NEVER independently gated — every
share saw them. This migration generalises the single enum into three flags so
a meeting can be shared as any subset of {transcript, insights, audio}:

    summary_and_transcript → (transcript=1, insights=1, audio=0)
    summary_only           → (transcript=0, insights=1, audio=0)

Both legacy scopes granted insights, so every back-filled row gets insights=1.
Audio (Task #30) was never share-able before, so it back-fills to 0. The old
`scope` column + its CHECK constraint are dropped; the API still accepts the old
enum for one release and maps it → flags before persisting.

Revision ID: 0024_meeting_share_artifact_flags
Revises: 0023_inperson_agenda
Create Date: 2026-06-30
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0024_meeting_share_artifact_flags"
down_revision = "0023_inperson_agenda"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Add the three flag columns. server_default="0" satisfies NOT NULL for
    #    the rows that already exist; the backfill UPDATEs below set the real
    #    values from the old `scope`.
    with op.batch_alter_table("meeting_shares") as batch:
        batch.add_column(
            sa.Column("share_transcript", sa.Integer, nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("share_insights", sa.Integer, nullable=False, server_default="0")
        )
        batch.add_column(
            sa.Column("share_audio", sa.Integer, nullable=False, server_default="0")
        )

    # 2. Backfill from the legacy scope. Both scopes granted insights.
    op.execute("UPDATE meeting_shares SET share_insights = 1")
    op.execute(
        "UPDATE meeting_shares SET share_transcript = 1 "
        "WHERE scope = 'summary_and_transcript'"
    )
    # share_audio stays 0 — audio was never shareable pre-#31.

    # 3. Drop the old enum column + its CHECK constraint.
    with op.batch_alter_table("meeting_shares") as batch:
        batch.drop_constraint("ck_meeting_shares_scope", type_="check")
        batch.drop_column("scope")


def downgrade() -> None:
    # Re-add the enum column and reconstruct its value from the flags
    # (transcript ⇒ summary_and_transcript, else summary_only), then drop flags.
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

    op.execute(
        "UPDATE meeting_shares SET scope = "
        "CASE WHEN share_transcript = 1 THEN 'summary_and_transcript' "
        "ELSE 'summary_only' END"
    )

    with op.batch_alter_table("meeting_shares") as batch:
        batch.drop_column("share_audio")
        batch.drop_column("share_insights")
        batch.drop_column("share_transcript")
