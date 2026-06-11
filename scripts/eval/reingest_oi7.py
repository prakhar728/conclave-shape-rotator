#!/usr/bin/env python3
"""OI-7 Commit 7 — re-ingest the cohort fixtures through the real pipeline into a
THROWAWAY DB with the fixed resolver, then check for black holes.

These fixtures are the cohort that produced the original black holes
(Dstack Intro Salon, TEE dstack easyTEE Phala, dstack hangout, …), so a clean
surface-count distribution here = the fix holds end-to-end.

Run: CONCLAVE_DB_PATH=/tmp/oi7_reingest.db ENABLE_KB_PIPELINE=1 \
     CONCLAVE_LLM_BACKEND=ollama python scripts/eval/reingest_oi7.py
"""
from __future__ import annotations

import glob
import os
import sys

DB = os.environ.setdefault("CONCLAVE_DB_PATH", "/tmp/oi7_reingest.db")
os.environ.setdefault("ENABLE_KB_PIPELINE", "1")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                 # for ingest_harness
sys.path.insert(0, os.path.join(_HERE, "..", ".."))

from ingest_harness import ensure_schema, ingest_meeting  # noqa: E402
from transcripts.kb_extract import extract_session         # noqa: E402
from transcripts.sources import read_file                  # noqa: E402
from check_entity_merge import flag_over_merged, surface_distribution  # noqa: E402

import sqlite3  # noqa: E402


def main() -> int:
    ensure_schema(DB)
    files = sorted(glob.glob("tests/fixtures/transcripts/*.txt"))
    print(f"re-ingesting {len(files)} cohort fixtures into {DB}")
    for i, f in enumerate(files):
        try:
            ni = read_file(f)
        except Exception as exc:  # noqa: BLE001
            print(f"  SKIP {f}: {exc}")
            continue
        segs = [{"speaker": s.get("speaker") or "", "text": s.get("text") or ""}
                for s in ni.segments if (s.get("text") or "").strip()]
        if not segs:
            print(f"  SKIP {f}: no segments")
            continue
        sid = f"oi7-reingest-{i}"
        ingest_meeting({"session_id": sid, "segments": segs})
        extract_session(sid)
        print(f"  done [{i+1}/{len(files)}] {os.path.basename(f)}  ({len(segs)} turns)")

    print("\n=== surface-count distribution (post-fix re-ingest) ===")
    conn = sqlite3.connect(DB)
    for surfaces, n in sorted(surface_distribution(conn).items()):
        print(f"  {surfaces:>3} surfaces : {n:>4} entities")
    flagged = flag_over_merged(conn, max_surfaces=10)
    print(f"\nblack holes (>10 surfaces): {len(flagged)}")
    for fl in flagged:
        print(f"  {fl['surfaces']} surf | [{fl['type']}] {fl['canonical_name']}")
    total = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    print(f"total entities: {total}")
    conn.close()
    return 0 if not flagged else 1


if __name__ == "__main__":
    raise SystemExit(main())
