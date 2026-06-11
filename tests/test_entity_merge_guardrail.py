"""Over-merge guardrail metric (OI-7 / EVAL.md E1).

Exercises `scripts/eval/check_entity_merge.flag_over_merged` on a synthetic DB:
a clean cohort stays unflagged; a planted "black hole" (one entity with many
distinct surfaces) is flagged. CI-safe — builds its own SQLite, never touches the
local cohort DB.
"""
from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "eval" / "check_entity_merge.py"
_spec = importlib.util.spec_from_file_location("check_entity_merge", _SCRIPT)
cem = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cem)  # type: ignore[union-attr]


def _db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE entities (
            id TEXT PRIMARY KEY, type TEXT, canonical_name TEXT,
            props_json TEXT, created_at TEXT
        );
        CREATE TABLE entity_mentions (
            id TEXT PRIMARY KEY, entity_id TEXT, session_id TEXT,
            turn_id INTEGER, raw_text TEXT, created_at TEXT
        );
        """
    )
    return conn


def _add_entity(conn, eid, etype, name, surfaces):
    conn.execute(
        "INSERT INTO entities (id, type, canonical_name) VALUES (?, ?, ?)",
        (eid, etype, name),
    )
    for i, surf in enumerate(surfaces):
        conn.execute(
            "INSERT INTO entity_mentions (id, entity_id, session_id, turn_id, raw_text)"
            " VALUES (?, ?, ?, ?, ?)",
            (f"{eid}-m{i}", eid, f"s{i % 3}", i, surf),
        )


def test_clean_cohort_is_not_flagged():
    conn = _db()
    # realistic clean shape: every entity at 1-3 distinct surfaces
    _add_entity(conn, "e1", "tool", "DStack", ["DStack", "dstack"])
    _add_entity(conn, "e2", "project", "Conclave", ["Conclave", "conclave", "the conclave app"])
    _add_entity(conn, "e3", "topic", "attestation", ["attestation"])
    assert cem.flag_over_merged(conn, max_surfaces=10) == []
    dist = cem.surface_distribution(conn)
    assert dist == {1: 1, 2: 1, 3: 1}


def test_black_hole_is_flagged():
    conn = _db()
    _add_entity(conn, "ok", "topic", "attestation", ["attestation", "remote attestation"])
    junk = [f"unrelated_surface_{i}" for i in range(40)]
    _add_entity(conn, "bh", "tool", "DStack", ["DStack", *junk])  # 41 distinct surfaces

    flagged = cem.flag_over_merged(conn, max_surfaces=10)
    assert [f["id"] for f in flagged] == ["bh"]
    assert flagged[0]["surfaces"] == 41
    assert flagged[0]["canonical_name"] == "DStack"
    # the clean entity is never flagged
    assert all(f["id"] != "ok" for f in flagged)


def test_threshold_is_respected():
    conn = _db()
    _add_entity(conn, "mid", "tool", "Mid", [f"s{i}" for i in range(7)])  # 7 surfaces
    assert cem.flag_over_merged(conn, max_surfaces=10) == []        # under cap
    assert [f["id"] for f in cem.flag_over_merged(conn, max_surfaces=5)] == ["mid"]
