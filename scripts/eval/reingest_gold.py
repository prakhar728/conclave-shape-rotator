#!/usr/bin/env python3
"""Re-ingest the 3 Codex-gold transcripts through the real pipeline + print the
per-transcript `extract`-stage wall-clock. Concurrency via
CONCLAVE_EXTRACT_CONCURRENCY (1 = sequential). Used for the OI-7 wall-clock A/B and
to populate the gold DB for `score_resolution_vs_gold.py`.

    CONCLAVE_DB_PATH=/tmp/gold_c6.db ENABLE_KB_PIPELINE=1 CONCLAVE_EXTRACT_CONCURRENCY=6 \
        python scripts/eval/reingest_gold.py [slug ...]
"""
from __future__ import annotations

import os
import sqlite3
import sys

os.environ.setdefault("ENABLE_KB_PIPELINE", "1")
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
sys.path.insert(0, os.path.join(_HERE, "..", ".."))

from ingest_harness import ensure_schema, ingest_meeting  # noqa: E402
from transcripts.kb_extract import extract_session          # noqa: E402
from transcripts.sources import read_file                   # noqa: E402

GOLD = {
    "dstack-intro-salon": "Dstack Intro Salon Session Transcript_May_20.txt",
    "elocute": "Elocute Transcript May 26.txt",
    "project-intros-agents-day3": "Project Intros Agents Day 3 Transcript_May_21.txt",
}


def main() -> int:
    slugs = sys.argv[1:] or list(GOLD)
    db = os.environ["CONCLAVE_DB_PATH"]
    ensure_schema(db)
    for slug in slugs:
        ni = read_file(f"tests/fixtures/transcripts/{GOLD[slug]}")
        segs = [{"speaker": s.get("speaker") or "", "text": s.get("text") or ""}
                for s in ni.segments if (s.get("text") or "").strip()]
        ingest_meeting({"session_id": slug, "segments": segs})
        extract_session(slug)
        print(f"  ingested {slug} ({len(segs)} turns)", flush=True)

    conn = sqlite3.connect(db)
    conc = os.environ.get("CONCLAVE_EXTRACT_CONCURRENCY", "default(6)")
    print(f"\n=== extract wall-clock (concurrency={conc}, db={db}) ===")
    for r in conn.execute(
        "SELECT session_id, ms_elapsed, llm_call_count FROM ingest_metrics"
        " WHERE stage='extract' ORDER BY session_id"
    ):
        print(f"  {r[1]/1000:7.1f}s  {r[2]:>2} chunks  {r[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
