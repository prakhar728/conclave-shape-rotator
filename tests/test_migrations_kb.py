"""Phase 3.5a C5 — migration 0006 applies cleanly and rolls back.

Runs against a throwaway DB file (NOT the conftest test DB, which is
already at head) so upgrade/downgrade can be exercised in isolation.

Skips when the running Python can't load sqlite-vec — the migration
hard-requires the extension for the chunks_vec virtual table.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from storage.vec import VEC_DIM, load_vec_extension


def _vec_loadable() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        return load_vec_extension(conn)
    finally:
        conn.close()


pytestmark = pytest.mark.skipif(
    not _vec_loadable(),
    reason="sqlite-vec not loadable in this interpreter "
           "(needs --enable-loadable-sqlite-extensions build)",
)


@pytest.fixture()
def alembic_db(monkeypatch):
    """Fresh DB upgraded to 0005, an AlembicConfig pointed at it."""
    from alembic.config import Config
    from alembic import command

    tmpdir = tempfile.mkdtemp(prefix="kb-mig-")
    db_path = os.path.join(tmpdir, "mig.db")

    # Legacy storage schema first (0004 ALTERs transcript_sessions).
    legacy = sqlite3.connect(db_path)
    from storage import sqlite as storage_sqlite
    storage_sqlite._init_schema(legacy)
    legacy.close()

    monkeypatch.setenv("CONCLAVE_DB_URL", f"sqlite:///{db_path}")
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(cfg, "0005_example_session")
    return cfg, db_path


def _tables(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','trigger')"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def test_0006_upgrade_creates_all_objects(alembic_db):
    from alembic import command
    cfg, db_path = alembic_db
    command.upgrade(cfg, "0006_embeddings_and_chunks")

    names = _tables(db_path)
    assert "chunks" in names
    assert "chunks_fts" in names
    assert "embeddings" in names
    assert "chunks_vec" in names
    assert {"chunks_fts_ai", "chunks_fts_ad", "chunks_fts_au"} <= names


def test_0006_fts_trigger_sync(alembic_db):
    from alembic import command
    cfg, db_path = alembic_db
    command.upgrade(cfg, "0006_embeddings_and_chunks")

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys=OFF")  # no real session row needed
        conn.execute(
            "INSERT INTO chunks (id, session_id, chunk_index, turn_ids, text,"
            " context_header, token_count, created_at)"
            " VALUES ('c1', 's1', 0, '[0,1]', 'the quick brown fox',"
            " 'a chunk about foxes', 4, '2026-06-03')"
        )
        hits = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'fox'"
        ).fetchall()
        assert len(hits) == 1

        # context_header is searchable too
        hits = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'foxes'"
        ).fetchall()
        assert len(hits) == 1

        conn.execute("DELETE FROM chunks WHERE id='c1'")
        hits = conn.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH 'fox'"
        ).fetchall()
        assert hits == []
    finally:
        conn.close()


def test_0006_vec_round_trip(alembic_db):
    from alembic import command
    cfg, db_path = alembic_db
    command.upgrade(cfg, "0006_embeddings_and_chunks")

    conn = sqlite3.connect(db_path)
    load_vec_extension(conn, required=True)
    try:
        import struct
        vec = struct.pack(f"{VEC_DIM}f", *([0.5] * VEC_DIM))
        conn.execute(
            "INSERT INTO chunks_vec(rowid, embedding) VALUES (1, ?)", (vec,)
        )
        row = conn.execute(
            "SELECT rowid, distance FROM chunks_vec"
            " WHERE embedding MATCH ? AND k = 1",
            (vec,),
        ).fetchone()
        assert row[0] == 1
        assert row[1] == pytest.approx(0.0, abs=1e-5)
    finally:
        conn.close()


def test_0006_downgrade_clean(alembic_db):
    from alembic import command
    cfg, db_path = alembic_db
    command.upgrade(cfg, "0006_embeddings_and_chunks")
    command.downgrade(cfg, "0005_example_session")

    names = _tables(db_path)
    assert "chunks" not in names
    assert "chunks_fts" not in names
    assert "embeddings" not in names
    assert "chunks_vec" not in names
    assert not {"chunks_fts_ai", "chunks_fts_ad", "chunks_fts_au"} & names
