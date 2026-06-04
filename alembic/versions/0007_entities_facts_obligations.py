"""Entity-fact graph layer + typed obligations (Phase 3.5b C12).

Four tables per KB-AND-GRAPH-ROADMAP-v2 §3 "Data model":

- ``entities``         — canonical entities (Q5 ER merges into these)
- ``entity_mentions``  — surface forms with provenance (session/turn/span)
- ``facts``            — typed subject–predicate–object rows, bi-temporal
- ``obligations``      — Q2: ONE table with a ``type`` enum
                         (action/decision/commitment/open_question/blocker),
                         bi-temporal like facts

Bi-temporal columns (``valid_from``/``valid_to``/``superseded_by``) are
nullable — populated by the Mem0 upsert path (Q10, C16): UPDATE sets the
old row's valid_to to the new row's valid_from; DELETE sets valid_to=now;
nothing is ever hard-deleted. "Current" rows are ``valid_to IS NULL``.

CHECK constraints keep enum drift out of the DB even if a future code
path forgets to validate. Importance is 1-10 (Q4).

Revision ID: 0007_entities_facts_obligations
Revises: 0006_embeddings_and_chunks
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_entities_facts_obligations"
down_revision = "0006_embeddings_and_chunks"
branch_labels = None
depends_on = None

ENTITY_TYPES = "('person','project','topic','company','tool')"
OBLIGATION_TYPES = "('action','decision','commitment','open_question','blocker')"
STATUS_VALUES = "('open','resolved','unclear')"


def upgrade() -> None:
    op.create_table(
        "entities",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("canonical_name", sa.Text, nullable=False),
        sa.Column("props_json", sa.Text, nullable=False, server_default="{}"),
        sa.Column("embedding_id", sa.Text, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.CheckConstraint(f"type IN {ENTITY_TYPES}", name="ck_entities_type"),
        sa.UniqueConstraint("type", "canonical_name", name="uq_entities_type_name"),
    )
    op.create_index("ix_entities_type", "entities", ["type"])
    op.create_index("ix_entities_name", "entities", ["canonical_name"])

    op.create_table(
        "entity_mentions",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("entity_id", sa.Text, sa.ForeignKey("entities.id"), nullable=False),
        sa.Column(
            "session_id", sa.Text,
            sa.ForeignKey("transcript_sessions.session_id"), nullable=False,
        ),
        sa.Column("turn_id", sa.Integer, nullable=True),
        sa.Column("raw_text", sa.Text, nullable=False),
        sa.Column("span_start", sa.Integer, nullable=True),
        sa.Column("span_end", sa.Integer, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("ix_mentions_entity", "entity_mentions", ["entity_id"])
    op.create_index("ix_mentions_session", "entity_mentions", ["session_id"])

    op.create_table(
        "facts",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("subject_entity_id", sa.Text, sa.ForeignKey("entities.id"), nullable=False),
        sa.Column("object_entity_id", sa.Text, sa.ForeignKey("entities.id"), nullable=True),
        sa.Column("predicate", sa.Text, nullable=False),
        sa.Column("source_quote", sa.Text, nullable=False, server_default=""),
        sa.Column("evidence_chunk_id", sa.Text, sa.ForeignKey("chunks.id"), nullable=True),
        sa.Column("valid_from", sa.Text, nullable=True),
        sa.Column("valid_to", sa.Text, nullable=True),
        sa.Column("superseded_by", sa.Text, sa.ForeignKey("facts.id"), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("importance", sa.Integer, nullable=True),
        sa.Column("model_version", sa.Text, nullable=True),
        sa.Column("ingested_at", sa.Text, nullable=False),
        sa.CheckConstraint(
            "importance IS NULL OR (importance >= 1 AND importance <= 10)",
            name="ck_facts_importance",
        ),
    )
    op.create_index("ix_facts_subject", "facts", ["subject_entity_id"])
    op.create_index("ix_facts_object", "facts", ["object_entity_id"])
    op.create_index("ix_facts_current", "facts", ["valid_to"])

    op.create_table(
        "obligations",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "session_id", sa.Text,
            sa.ForeignKey("transcript_sessions.session_id"), nullable=False,
        ),
        sa.Column("turn_ids", sa.Text, nullable=False, server_default="[]"),  # JSON
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("source_quote", sa.Text, nullable=False, server_default=""),
        sa.Column("owner_entity_id", sa.Text, sa.ForeignKey("entities.id"), nullable=True),
        sa.Column("owner_raw_text", sa.Text, nullable=True),
        sa.Column("assignee_evidence", sa.Text, nullable=True),
        sa.Column("due_date_iso", sa.Text, nullable=True),
        sa.Column("due_date_raw", sa.Text, nullable=True),
        sa.Column("status_inferred", sa.Text, nullable=False, server_default="unclear"),
        sa.Column("valid_from", sa.Text, nullable=True),
        sa.Column("valid_to", sa.Text, nullable=True),
        sa.Column("superseded_by", sa.Text, sa.ForeignKey("obligations.id"), nullable=True),
        sa.Column("confidence", sa.Float, nullable=True),
        sa.Column("importance", sa.Integer, nullable=True),
        sa.Column("model_version", sa.Text, nullable=True),
        sa.Column("ingested_at", sa.Text, nullable=False),
        sa.CheckConstraint(f"type IN {OBLIGATION_TYPES}", name="ck_obligations_type"),
        sa.CheckConstraint(
            f"status_inferred IN {STATUS_VALUES}", name="ck_obligations_status"
        ),
        sa.CheckConstraint(
            "importance IS NULL OR (importance >= 1 AND importance <= 10)",
            name="ck_obligations_importance",
        ),
    )
    op.create_index("ix_obligations_session", "obligations", ["session_id"])
    op.create_index("ix_obligations_type", "obligations", ["type"])
    op.create_index("ix_obligations_owner", "obligations", ["owner_entity_id"])
    op.create_index("ix_obligations_status", "obligations", ["status_inferred"])
    op.create_index("ix_obligations_current", "obligations", ["valid_to"])


def downgrade() -> None:
    for ix, table in (
        ("ix_obligations_current", "obligations"),
        ("ix_obligations_status", "obligations"),
        ("ix_obligations_owner", "obligations"),
        ("ix_obligations_type", "obligations"),
        ("ix_obligations_session", "obligations"),
    ):
        op.drop_index(ix, table_name=table)
    op.drop_table("obligations")
    for ix in ("ix_facts_current", "ix_facts_object", "ix_facts_subject"):
        op.drop_index(ix, table_name="facts")
    op.drop_table("facts")
    for ix in ("ix_mentions_session", "ix_mentions_entity"):
        op.drop_index(ix, table_name="entity_mentions")
    op.drop_table("entity_mentions")
    for ix in ("ix_entities_name", "ix_entities_type"):
        op.drop_index(ix, table_name="entities")
    op.drop_table("entities")
