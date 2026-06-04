"""sqlite-vec extension loading — shared by storage and Alembic (3.5a C5).

One function, one policy: try to load, return whether it worked. The
storage layer treats absence as a soft failure (app boots, vector search
unavailable); migration 0006 treats it as hard (the chunks_vec virtual
table cannot be created without the extension, so migrating without it
would leave a half-applied schema).

Requires a Python built with loadable-extension support
(``--enable-loadable-sqlite-extensions``); see transcripts/OLLAMA.md
companion note and Phase 3.5a C5 commit message for the pyenv rebuild
that this project needed on macOS.
"""
from __future__ import annotations

import logging
import sqlite3

log = logging.getLogger(__name__)

#: Embedding dimension for the primary vector index (Matryoshka-truncated
#: nomic-embed-text v1.5 — Survey D18; full 768 recomputable on demand).
VEC_DIM = 256


def load_vec_extension(conn: sqlite3.Connection, *, required: bool = False) -> bool:
    """Load sqlite-vec into ``conn``. Returns True on success.

    ``required=True`` raises instead of returning False — used by the
    migration, where proceeding without the extension would half-apply
    the schema.
    """
    if not hasattr(conn, "enable_load_extension"):
        msg = (
            "this Python's sqlite3 lacks loadable-extension support "
            "(build with --enable-loadable-sqlite-extensions)"
        )
        if required:
            raise RuntimeError(msg)
        log.warning("sqlite-vec unavailable: %s", msg)
        return False
    try:
        import sqlite_vec
    except ImportError as exc:
        if required:
            raise RuntimeError(f"sqlite-vec not installed: {exc}") from exc
        log.warning("sqlite-vec unavailable: %s", exc)
        return False
    try:
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
    finally:
        # Never leave generic extension loading enabled — sqlite-vec is the
        # only extension this app loads.
        conn.enable_load_extension(False)
    return True


def vec_available(conn: sqlite3.Connection) -> bool:
    """True when vec0 is usable on this connection."""
    try:
        conn.execute("SELECT vec_version()")
        return True
    except sqlite3.OperationalError:
        return False
