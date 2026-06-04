"""Ingest cost tracking table (Phase 3.5b C17-pre).

Build plan places ingest_metrics inside C17; ground rule 2 ("migrations
are their own commit") wins, so the table ships one commit ahead of the
pipeline that writes it. C38 adds the viewer endpoint.

One row per (session, stage) per pipeline run: stage name, LLM call
count, wall-clock ms. The roadmap's cost-budget table (§7) gets its
real numbers from here.

Revision ID: 0008_ingest_metrics
Revises: 0007_entities_facts_obligations
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_ingest_metrics"
down_revision = "0007_entities_facts_obligations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ingest_metrics",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.Text, nullable=False),
        sa.Column("stage", sa.Text, nullable=False),
        sa.Column("llm_call_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("ms_elapsed", sa.Integer, nullable=False, server_default="0"),
        sa.Column("items_in", sa.Integer, nullable=True),
        sa.Column("items_out", sa.Integer, nullable=True),
        sa.Column("created_at", sa.Text, nullable=False),
    )
    op.create_index("ix_ingest_metrics_session", "ingest_metrics", ["session_id"])
    op.create_index("ix_ingest_metrics_stage", "ingest_metrics", ["stage"])


def downgrade() -> None:
    op.drop_index("ix_ingest_metrics_stage", table_name="ingest_metrics")
    op.drop_index("ix_ingest_metrics_session", table_name="ingest_metrics")
    op.drop_table("ingest_metrics")
