#!/usr/bin/env python3
"""Entity over-merge guardrail (OI-7 / EVAL.md E1).

A standing check for "black-hole" entities — rows that have absorbed far more
distinct surface forms than any real entity should. In the cohort DB the healthy
distribution is a sharp cliff (every real entity sits at 1-3 distinct surfaces),
so a handful of entities at 46/52/75/94 surfaces is a reliable over-merge
signature, not messy data.

This promotes the ad-hoc diagnostic that first exposed OI-7 into a reusable,
checkable metric. It measures **resolution quality** (over-merge), the dimension
the extraction-F1 bake-off is structurally blind to: F1 scores extraction per
single transcript and matches on canonical_name, so a black hole still matches
its gold head and the junk surfaces never move the score.

Pure read. Importable (`flag_over_merged`, `surface_distribution`) for tests, or
run as a CLI against a DB:

    python scripts/eval/check_entity_merge.py --db data/conclave.db
    python scripts/eval/check_entity_merge.py --db data/conclave.diag.bak --max-surfaces 10

Exit code is non-zero when any entity exceeds the surface cap, so it doubles as a
CI/pre-merge guardrail.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys

#: Distinct-surface cap above which an entity is flagged as a likely over-merge.
#: The real cliff sits at ~3 surfaces; 10 leaves generous headroom for a
#: genuinely high-frequency entity while still catching the 46+ black holes.
DEFAULT_MAX_SURFACES = 10


def _rows(conn: sqlite3.Connection):
    conn.row_factory = sqlite3.Row
    return conn.execute(
        """
        SELECT e.id, e.type, e.canonical_name,
               COUNT(DISTINCT m.raw_text) AS surfaces,
               COUNT(*)                   AS mentions,
               COUNT(DISTINCT m.session_id) AS sessions
        FROM entities e JOIN entity_mentions m ON m.entity_id = e.id
        GROUP BY e.id
        ORDER BY surfaces DESC, mentions DESC
        """
    ).fetchall()


def flag_over_merged(
    conn: sqlite3.Connection, *, max_surfaces: int = DEFAULT_MAX_SURFACES
) -> list[dict]:
    """Return entities whose distinct-surface count exceeds ``max_surfaces``.

    Each dict: ``{id, type, canonical_name, surfaces, mentions, sessions}``,
    sorted most-corrupt first. Empty list == clean.
    """
    return [
        {
            "id": r["id"], "type": r["type"], "canonical_name": r["canonical_name"],
            "surfaces": r["surfaces"], "mentions": r["mentions"],
            "sessions": r["sessions"],
        }
        for r in _rows(conn)
        if r["surfaces"] > max_surfaces
    ]


def surface_distribution(conn: sqlite3.Connection) -> dict[int, int]:
    """Histogram: ``{distinct_surface_count -> number_of_entities}``."""
    conn.row_factory = sqlite3.Row
    hist: dict[int, int] = {}
    for r in conn.execute(
        "SELECT surfaces, COUNT(*) AS n FROM ("
        "  SELECT entity_id, COUNT(DISTINCT raw_text) AS surfaces"
        "  FROM entity_mentions GROUP BY entity_id"
        ") GROUP BY surfaces ORDER BY surfaces"
    ).fetchall():
        hist[r["surfaces"]] = r["n"]
    return hist


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="data/conclave.db", help="SQLite DB path")
    ap.add_argument("--max-surfaces", type=int, default=DEFAULT_MAX_SURFACES)
    args = ap.parse_args(argv)

    conn = sqlite3.connect(args.db)
    try:
        dist = surface_distribution(conn)
        flagged = flag_over_merged(conn, max_surfaces=args.max_surfaces)
    finally:
        conn.close()

    print(f"surface-count distribution (db={args.db}):")
    for surfaces, n in sorted(dist.items()):
        bar = "  <== over cap" if surfaces > args.max_surfaces else ""
        print(f"  {surfaces:>4} surfaces : {n:>4} entities{bar}")

    if flagged:
        print(f"\nFLAGGED {len(flagged)} entity(ies) over {args.max_surfaces} surfaces "
              "(likely over-merge / black holes):")
        for f in flagged:
            print(f"  {f['surfaces']:>3} surf | {f['mentions']:>4} ment | "
                  f"[{f['type']}] {f['canonical_name']}")
        return 1

    print(f"\nOK — no entity exceeds {args.max_surfaces} distinct surfaces.")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
