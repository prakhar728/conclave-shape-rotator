"""Phase 3.5b C12 — migration 0007 applies + rolls back + constraints hold."""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from storage.vec import load_vec_extension


def _vec_loadable() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        return load_vec_extension(conn)
    finally:
        conn.close()


pytestmark = pytest.mark.skipif(
    not _vec_loadable(),
    reason="sqlite-vec not loadable (0007 sits above 0006 which needs it)",
)


@pytest.fixture()
def alembic_db(monkeypatch):
    from alembic.config import Config
    from alembic import command

    tmpdir = tempfile.mkdtemp(prefix="kb-mig7-")
    db_path = os.path.join(tmpdir, "mig.db")

    legacy = sqlite3.connect(db_path)
    from storage import sqlite as storage_sqlite
    storage_sqlite._init_schema(legacy)
    legacy.close()

    monkeypatch.setenv("CONCLAVE_DB_URL", f"sqlite:///{db_path}")
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    command.upgrade(cfg, "0007_entities_facts_obligations")
    return cfg, db_path


def _conn(db_path: str) -> sqlite3.Connection:
    c = sqlite3.connect(db_path)
    c.execute("PRAGMA foreign_keys=ON")
    return c


def test_0007_tables_exist(alembic_db):
    _, db_path = alembic_db
    conn = _conn(db_path)
    names = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert {"entities", "entity_mentions", "facts", "obligations"} <= names
    conn.close()


def test_0007_enum_checks_enforced(alembic_db):
    _, db_path = alembic_db
    conn = _conn(db_path)
    conn.execute(
        "INSERT INTO entities (id, type, canonical_name, created_at)"
        " VALUES ('e1', 'person', 'Ada', '2026-06-04')"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO entities (id, type, canonical_name, created_at)"
            " VALUES ('e2', 'alien', 'Zorp', '2026-06-04')"
        )
    with pytest.raises(sqlite3.IntegrityError):  # bad obligation type
        conn.execute(
            "INSERT INTO obligations (id, session_id, type, description, ingested_at)"
            " VALUES ('o1', 's1', 'wish', 'x', '2026-06-04')"
        )
    with pytest.raises(sqlite3.IntegrityError):  # importance out of range
        conn.execute(
            "INSERT INTO obligations (id, session_id, type, description,"
            " importance, ingested_at)"
            " VALUES ('o2', 's1', 'action', 'x', 11, '2026-06-04')"
        )
    conn.close()


def test_0007_unique_entity_and_bitemporal_chain(alembic_db):
    _, db_path = alembic_db
    conn = _conn(db_path)
    conn.execute(
        "INSERT INTO entities (id, type, canonical_name, created_at)"
        " VALUES ('e1', 'project', 'Elocute', 't')"
    )
    with pytest.raises(sqlite3.IntegrityError):  # (type, name) unique
        conn.execute(
            "INSERT INTO entities (id, type, canonical_name, created_at)"
            " VALUES ('e2', 'project', 'Elocute', 't')"
        )
    # bi-temporal supersession chain on facts
    conn.execute("PRAGMA foreign_keys=OFF")
    conn.execute(
        "INSERT INTO facts (id, type, subject_entity_id, predicate, ingested_at,"
        " valid_from) VALUES ('f1', 'works_on', 'e1', 'works_on', 't', '2026-06-01')"
    )
    conn.execute(
        "INSERT INTO facts (id, type, subject_entity_id, predicate, ingested_at,"
        " valid_from) VALUES ('f2', 'works_on', 'e1', 'works_on', 't', '2026-06-04')"
    )
    conn.execute(
        "UPDATE facts SET valid_to='2026-06-04', superseded_by='f2' WHERE id='f1'"
    )
    current = conn.execute(
        "SELECT id FROM facts WHERE valid_to IS NULL"
    ).fetchall()
    assert [r[0] for r in current] == ["f2"]
    conn.close()


def test_0007_downgrade_clean(alembic_db):
    from alembic import command
    cfg, db_path = alembic_db
    command.downgrade(cfg, "0006_embeddings_and_chunks")
    conn = _conn(db_path)
    names = {
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    assert not {"entities", "entity_mentions", "facts", "obligations"} & names
    assert "chunks" in names  # 0006 untouched
    conn.close()
