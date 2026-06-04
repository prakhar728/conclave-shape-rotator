"""ON DELETE CASCADE for KB child tables (3.5f C37 drift fix).

chunks / entity_mentions / obligations reference transcript_sessions;
without cascade, a hard session delete (tests, admin cleanup) trips
FOREIGN KEY constraint failures — surfaced as cross-test pollution in
the C37 sweep (pre-existing tests do bare DELETE FROM
transcript_sessions).

Sessions are the immutable root of the data model: a KB child row has
no meaning after its session is gone, so CASCADE is semantically right.
(Bi-temporal never-hard-delete discipline governs the obligations
*lifecycle* via valid_to — not raw session removal.)
facts.evidence_chunk_id → chunks becomes SET NULL: a fact may outlive
its evidence pointer.

The 0006/0007 FKs are unnamed (inline sa.ForeignKey), so batch-mode
drop_constraint can't address them — each table is rebuilt with raw
SQL instead. chunks copies rowid explicitly (chunks_vec is keyed by
chunks.rowid; the FTS5 external-content table also addresses by
rowid), and the three FTS triggers are recreated after the rename.

Revision ID: 0010_kb_fk_cascade
Revises: 0009_example_workspace
Create Date: 2026-06-04
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_kb_fk_cascade"
down_revision = "0009_example_workspace"
branch_labels = None
depends_on = None


_CHUNKS_DDL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES transcript_sessions (session_id) ON DELETE {sess_action},
    chunk_index INTEGER NOT NULL,
    turn_ids TEXT NOT NULL,
    text TEXT NOT NULL,
    context_header TEXT NOT NULL DEFAULT '',
    token_count INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    CONSTRAINT uq_chunks_session_index UNIQUE (session_id, chunk_index)
)
"""

_MENTIONS_DDL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY,
    entity_id TEXT NOT NULL REFERENCES entities (id) ON DELETE {ent_action},
    session_id TEXT NOT NULL REFERENCES transcript_sessions (session_id) ON DELETE {sess_action},
    turn_id INTEGER,
    raw_text TEXT NOT NULL,
    span_start INTEGER,
    span_end INTEGER,
    created_at TEXT NOT NULL
)
"""

_OBLIGATIONS_DDL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES transcript_sessions (session_id) ON DELETE {sess_action},
    turn_ids TEXT NOT NULL DEFAULT '[]',
    type TEXT NOT NULL,
    description TEXT NOT NULL,
    source_quote TEXT NOT NULL DEFAULT '',
    owner_entity_id TEXT REFERENCES entities (id),
    owner_raw_text TEXT,
    assignee_evidence TEXT,
    due_date_iso TEXT,
    due_date_raw TEXT,
    status_inferred TEXT NOT NULL DEFAULT 'unclear',
    valid_from TEXT,
    valid_to TEXT,
    superseded_by TEXT REFERENCES obligations (id),
    confidence FLOAT,
    importance INTEGER,
    model_version TEXT,
    ingested_at TEXT NOT NULL,
    CONSTRAINT ck_obligations_type CHECK (type IN ('action','decision','commitment','open_question','blocker')),
    CONSTRAINT ck_obligations_status CHECK (status_inferred IN ('open','resolved','unclear')),
    CONSTRAINT ck_obligations_importance CHECK (importance IS NULL OR (importance >= 1 AND importance <= 10))
)
"""

_FACTS_DDL = """
CREATE TABLE {name} (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    subject_entity_id TEXT NOT NULL REFERENCES entities (id),
    object_entity_id TEXT REFERENCES entities (id),
    predicate TEXT NOT NULL,
    source_quote TEXT NOT NULL DEFAULT '',
    evidence_chunk_id TEXT REFERENCES chunks (id) ON DELETE {chunk_action},
    valid_from TEXT,
    valid_to TEXT,
    superseded_by TEXT REFERENCES facts (id),
    confidence FLOAT,
    importance INTEGER,
    model_version TEXT,
    ingested_at TEXT NOT NULL,
    CONSTRAINT ck_facts_importance CHECK (importance IS NULL OR (importance >= 1 AND importance <= 10))
)
"""

_FTS_TRIGGERS = [
    """CREATE TRIGGER chunks_fts_ai AFTER INSERT ON chunks BEGIN
        INSERT INTO chunks_fts(rowid, text, context_header)
        VALUES (new.rowid, new.text, new.context_header);
    END""",
    """CREATE TRIGGER chunks_fts_ad AFTER DELETE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, text, context_header)
        VALUES ('delete', old.rowid, old.text, old.context_header);
    END""",
    """CREATE TRIGGER chunks_fts_au AFTER UPDATE ON chunks BEGIN
        INSERT INTO chunks_fts(chunks_fts, rowid, text, context_header)
        VALUES ('delete', old.rowid, old.text, old.context_header);
        INSERT INTO chunks_fts(rowid, text, context_header)
        VALUES (new.rowid, new.text, new.context_header);
    END""",
]

_CHUNK_COLS = "id, session_id, chunk_index, turn_ids, text, context_header, token_count, created_at"
_MENTION_COLS = "id, entity_id, session_id, turn_id, raw_text, span_start, span_end, created_at"
_OBLIGATION_COLS = ("id, session_id, turn_ids, type, description, source_quote,"
                    " owner_entity_id, owner_raw_text, assignee_evidence, due_date_iso,"
                    " due_date_raw, status_inferred, valid_from, valid_to, superseded_by,"
                    " confidence, importance, model_version, ingested_at")
_FACT_COLS = ("id, type, subject_entity_id, object_entity_id, predicate, source_quote,"
              " evidence_chunk_id, valid_from, valid_to, superseded_by, confidence,"
              " importance, model_version, ingested_at")


def _rebuild_all(sess_action: str, ent_action: str, chunk_action: str) -> None:
    conn = op.get_bind()
    x = conn.execute
    x(sa.text("PRAGMA foreign_keys=OFF"))

    # chunks — rowid preserved (chunks_vec + chunks_fts address by rowid)
    x(sa.text(_CHUNKS_DDL.format(name="chunks_new", sess_action=sess_action)))
    x(sa.text(f"INSERT INTO chunks_new (rowid, {_CHUNK_COLS})"
              f" SELECT rowid, {_CHUNK_COLS} FROM chunks"))
    for trig in ("chunks_fts_ai", "chunks_fts_ad", "chunks_fts_au"):
        x(sa.text(f"DROP TRIGGER IF EXISTS {trig}"))
    x(sa.text("DROP TABLE chunks"))
    x(sa.text("ALTER TABLE chunks_new RENAME TO chunks"))
    x(sa.text("CREATE INDEX ix_chunks_session_id ON chunks (session_id)"))
    for ddl in _FTS_TRIGGERS:
        x(sa.text(ddl))

    # entity_mentions
    x(sa.text(_MENTIONS_DDL.format(name="entity_mentions_new",
                                   ent_action=ent_action, sess_action=sess_action)))
    x(sa.text(f"INSERT INTO entity_mentions_new ({_MENTION_COLS})"
              f" SELECT {_MENTION_COLS} FROM entity_mentions"))
    x(sa.text("DROP TABLE entity_mentions"))
    x(sa.text("ALTER TABLE entity_mentions_new RENAME TO entity_mentions"))
    x(sa.text("CREATE INDEX ix_mentions_entity ON entity_mentions (entity_id)"))
    x(sa.text("CREATE INDEX ix_mentions_session ON entity_mentions (session_id)"))

    # obligations
    x(sa.text(_OBLIGATIONS_DDL.format(name="obligations_new", sess_action=sess_action)))
    x(sa.text(f"INSERT INTO obligations_new ({_OBLIGATION_COLS})"
              f" SELECT {_OBLIGATION_COLS} FROM obligations"))
    x(sa.text("DROP TABLE obligations"))
    x(sa.text("ALTER TABLE obligations_new RENAME TO obligations"))
    x(sa.text("CREATE INDEX ix_obligations_session ON obligations (session_id)"))
    x(sa.text("CREATE INDEX ix_obligations_type ON obligations (type)"))
    x(sa.text("CREATE INDEX ix_obligations_owner ON obligations (owner_entity_id)"))
    x(sa.text("CREATE INDEX ix_obligations_status ON obligations (status_inferred)"))
    x(sa.text("CREATE INDEX ix_obligations_current ON obligations (valid_to)"))

    # facts
    x(sa.text(_FACTS_DDL.format(name="facts_new", chunk_action=chunk_action)))
    x(sa.text(f"INSERT INTO facts_new ({_FACT_COLS}) SELECT {_FACT_COLS} FROM facts"))
    x(sa.text("DROP TABLE facts"))
    x(sa.text("ALTER TABLE facts_new RENAME TO facts"))
    x(sa.text("CREATE INDEX ix_facts_subject ON facts (subject_entity_id)"))
    x(sa.text("CREATE INDEX ix_facts_object ON facts (object_entity_id)"))
    x(sa.text("CREATE INDEX ix_facts_current ON facts (valid_to)"))

    x(sa.text("PRAGMA foreign_keys=ON"))


def upgrade() -> None:
    _rebuild_all(sess_action="CASCADE", ent_action="CASCADE", chunk_action="SET NULL")


def downgrade() -> None:
    _rebuild_all(sess_action="NO ACTION", ent_action="NO ACTION", chunk_action="NO ACTION")
