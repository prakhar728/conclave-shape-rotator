"""Part 1 data-foundation migration (0015) — applies, rolls back, at head.

Throwaway DB (NOT the conftest DB, which is already at head) so up/down run in
isolation. The full chain to 0015 passes through 0006 (chunks_vec), so this
module needs sqlite-vec loadable — same guard as the kb migration tests.
"""
from __future__ import annotations

import os
import sqlite3
import tempfile

import pytest

from storage.vec import load_vec_extension

EXPECTED_V2_OBJECTS = {"transcript_v2", "vocab"}
HEAD = "0015_transcript_v2_and_vocab"
PREV = "0014_bot_invitation_intent"


def _vec_loadable() -> bool:
    conn = sqlite3.connect(":memory:")
    try:
        return load_vec_extension(conn)
    finally:
        conn.close()


pytestmark = pytest.mark.skipif(
    not _vec_loadable(),
    reason="sqlite-vec not loadable (the 0004->0015 chain runs 0006 chunks_vec)",
)


@pytest.fixture()
def alembic_db(monkeypatch):
    """Fresh legacy-schema DB + an AlembicConfig pointed at it (not yet migrated)."""
    from alembic.config import Config

    tmpdir = tempfile.mkdtemp(prefix="v2-mig-")
    db_path = os.path.join(tmpdir, "mig.db")

    legacy = sqlite3.connect(db_path)
    from storage import sqlite as storage_sqlite
    storage_sqlite._init_schema(legacy)
    legacy.close()

    monkeypatch.setenv("CONCLAVE_DB_URL", f"sqlite:///{db_path}")
    cfg = Config(os.path.join(os.path.dirname(__file__), "..", "alembic.ini"))
    return cfg, db_path


def _tables(db_path: str) -> set[str]:
    conn = sqlite3.connect(db_path)
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        return {r[0] for r in rows}
    finally:
        conn.close()


def test_0015_upgrade_creates_v2_and_vocab(alembic_db):  # M-1
    from alembic import command
    cfg, db_path = alembic_db
    command.upgrade(cfg, HEAD)
    assert EXPECTED_V2_OBJECTS <= _tables(db_path)


def test_0015_downgrade_clean_and_idempotent(alembic_db):  # M-2
    from alembic import command
    cfg, db_path = alembic_db
    command.upgrade(cfg, HEAD)
    command.downgrade(cfg, PREV)
    assert not (EXPECTED_V2_OBJECTS & _tables(db_path))
    # re-upgrade after downgrade must succeed (no leftover objects)
    command.upgrade(cfg, HEAD)
    assert EXPECTED_V2_OBJECTS <= _tables(db_path)


def test_0015_present_at_conftest_head():  # M-3
    # conftest upgrades the per-process test DB to head at import; the new
    # tables must be reachable on the live connection.
    from storage import sqlite as storage_sqlite
    rows = storage_sqlite._get_conn().execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    assert EXPECTED_V2_OBJECTS <= {r[0] for r in rows}
