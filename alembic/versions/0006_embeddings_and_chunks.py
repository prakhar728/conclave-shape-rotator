"""Chunking + hybrid retrieval foundation (Phase 3.5a C5).

Four tables per KB-AND-GRAPH-ROADMAP-v2 §3 "Data model":

- ``chunks``      — turn-aware chunk rows (turn_ids JSON, context_header)
- ``chunks_fts``  — FTS5 over text + context_header, external-content
                    against ``chunks`` with trigger-maintained sync
- ``embeddings``  — model-keyed vectors (A/B embedding models without
                    re-ingest; Survey recommendation)
- ``chunks_vec``  — sqlite-vec vec0 virtual table, 256-dim primary
                    (Matryoshka-truncated nomic-embed-text v1.5, D18)

The vec0 table REQUIRES the sqlite-vec extension on the migration
connection — ``storage.vec.load_vec_extension(required=True)`` raises
rather than half-applying. FTS5 ships in stock SQLite.

``chunks_vec`` rows are keyed by ``chunks.rowid`` (vec0 rowid ==
chunks.rowid); sync is the storage layer's job (delete-then-insert per
session), NOT triggers — embedding writes happen well after chunk
writes, so trigger-time sync is impossible anyway.

Revision ID: 0006_embeddings_and_chunks
Revises: 0005_example_session
Create Date: 2026-06-03
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from storage.vec import VEC_DIM, load_vec_extension

revision = "0006_embeddings_and_chunks"
down_revision = "0005_example_session"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # --- chunks ------------------------------------------------------------
    op.create_table(
        "chunks",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column(
            "session_id", sa.Text,
            sa.ForeignKey("transcript_sessions.session_id"), nullable=False,
        ),
        sa.Column("chunk_index", sa.Integer, nullable=False),
        sa.Column("turn_ids", sa.Text, nullable=False),  # JSON int array
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("context_header", sa.Text, nullable=False, server_default=""),
        sa.Column("token_count", sa.Integer, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.UniqueConstraint("session_id", "chunk_index", name="uq_chunks_session_index"),
    )
    op.create_index("ix_chunks_session_id", "chunks", ["session_id"])

    # --- chunks_fts (FTS5, external content, trigger-synced) ----------------
    op.execute(
        """
        CREATE VIRTUAL TABLE chunks_fts USING fts5(
            text,
            context_header,
            content='chunks',
            content_rowid='rowid'
        )
        """
    )
    op.execute(
        """
        CREATE TRIGGER chunks_fts_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, text, context_header)
            VALUES (new.rowid, new.text, new.context_header);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER chunks_fts_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, text, context_header)
            VALUES ('delete', old.rowid, old.text, old.context_header);
        END
        """
    )
    op.execute(
        """
        CREATE TRIGGER chunks_fts_au AFTER UPDATE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, text, context_header)
            VALUES ('delete', old.rowid, old.text, old.context_header);
            INSERT INTO chunks_fts(rowid, text, context_header)
            VALUES (new.rowid, new.text, new.context_header);
        END
        """
    )

    # --- embeddings ----------------------------------------------------------
    op.create_table(
        "embeddings",
        sa.Column("id", sa.Text, primary_key=True),
        sa.Column("source_kind", sa.Text, nullable=False),  # 'chunk'|'obligation'|'entity'
        sa.Column("source_id", sa.Text, nullable=False),
        sa.Column("model_id", sa.Text, nullable=False),
        sa.Column("dim", sa.Integer, nullable=False),
        sa.Column("vec", sa.LargeBinary, nullable=False),
        sa.Column("created_at", sa.Text, nullable=False),
        sa.UniqueConstraint(
            "source_kind", "source_id", "model_id",
            name="uq_embeddings_source_model",
        ),
    )
    op.create_index("ix_embeddings_source", "embeddings", ["source_kind", "source_id"])
    op.create_index("ix_embeddings_model", "embeddings", ["model_id"])

    # --- chunks_vec (sqlite-vec) ---------------------------------------------
    raw = op.get_bind().connection.driver_connection
    load_vec_extension(raw, required=True)
    op.execute(
        f"CREATE VIRTUAL TABLE chunks_vec USING vec0(embedding float[{VEC_DIM}])"
    )


def downgrade() -> None:
    # Dropping a vec0 virtual table also needs the module present.
    raw = op.get_bind().connection.driver_connection
    load_vec_extension(raw, required=True)
    op.execute("DROP TABLE IF EXISTS chunks_vec")
    op.drop_index("ix_embeddings_model", table_name="embeddings")
    op.drop_index("ix_embeddings_source", table_name="embeddings")
    op.drop_table("embeddings")
    op.execute("DROP TRIGGER IF EXISTS chunks_fts_au")
    op.execute("DROP TRIGGER IF EXISTS chunks_fts_ad")
    op.execute("DROP TRIGGER IF EXISTS chunks_fts_ai")
    op.execute("DROP TABLE IF EXISTS chunks_fts")
    op.drop_index("ix_chunks_session_id", table_name="chunks")
    op.drop_table("chunks")
