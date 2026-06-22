"""Part 1 (transcript refinement) data foundation: v2 draft + per-user vocab.

Two tables per `docs/plans/transcript-refine.md` §12 LOCKED #1/#2:

- ``transcript_v2``  — the editable, span-annotated correction layer that lives
                       ALONGSIDE the immutable ``transcript_sessions.raw_diarization``.
                       One row per session: ``status`` (draft→approved) + a
                       ``doc_json`` blob holding segments mirroring raw, with
                       token/segment-relative span annotations (the editor's
                       ground truth). Raw is never touched; edits land here.
- ``vocab``          — the per-user dictionary (§2). ``surface_norm`` is the
                       normalized lookup key; PRIMARY KEY (user_id, surface_norm)
                       gives the O(1) hashmap + upsert contract. Powers the
                       suggestion flywheel; kept separate from the global
                       ``entities`` graph so Part 1 stays per-user + decoupled.

Trust-state lands in its own later migration (the ramp-up slice), per the
per-increment build plan. Nullable/new tables only → existing rows untouched.

Revision ID: 0015_transcript_v2_and_vocab
Revises: 0014_bot_invitation_intent
Create Date: 2026-06-19
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_transcript_v2_and_vocab"
down_revision = "0014_bot_invitation_intent"
branch_labels = None
depends_on = None

V2_STATUS = "('draft','approved')"


def upgrade() -> None:
    op.create_table(
        "transcript_v2",
        sa.Column(
            "session_id", sa.Text,
            sa.ForeignKey("transcript_sessions.session_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("status", sa.Text, nullable=False, server_default="draft"),
        sa.Column("doc_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("approved_at", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.CheckConstraint(f"status IN {V2_STATUS}", name="ck_transcript_v2_status"),
    )

    op.create_table(
        "vocab",
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("surface_norm", sa.Text, nullable=False),
        sa.Column("is_entity", sa.Integer, nullable=False, server_default="0"),
        sa.Column("type", sa.Text, nullable=True),
        sa.Column("canonical_id", sa.Text, nullable=True),
        sa.Column("provenance", sa.Text, nullable=False, server_default="user"),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.Column("updated_at", sa.Text, nullable=False),
        sa.PrimaryKeyConstraint("user_id", "surface_norm", name="pk_vocab"),
    )
    op.create_index("ix_vocab_user", "vocab", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_vocab_user", table_name="vocab")
    op.drop_table("vocab")
    op.drop_table("transcript_v2")
