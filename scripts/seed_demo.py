#!/usr/bin/env python3
"""Build KB artifacts for the 0009 demo sessions (3.5e C35).

Run AFTER `alembic upgrade head` (which seeds the raw demo sessions
from the fixture transcripts). This script runs the two pipelines the
migration must not (they call Ollama / the LLM backend):

    1. kb_pipeline.index_session   — chunks + FTS + embeddings
    2. kb_extract.extract_session  — entities/obligations (needs
                                     ENABLE_KB_PIPELINE=1)

Idempotent — both pipelines replace/upsert.

Usage:
    ENABLE_KB_PIPELINE=1 python3 scripts/seed_demo.py [--headers] [--skip-extract]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DEMO_IDS = [
    "demo-elocute",
    "demo-dstack-intro-salon",
    "demo-project-intros-agents-day3",
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headers", action="store_true",
                    help="generate context headers (LLM call per chunk)")
    ap.add_argument("--skip-extract", action="store_true",
                    help="only chunk+embed; skip entity/obligation extraction")
    args = ap.parse_args()

    from transcripts import store
    from transcripts.kb_pipeline import index_session
    from transcripts.kb_extract import extract_session, kb_pipeline_enabled

    if not args.skip_extract and not kb_pipeline_enabled():
        print("ENABLE_KB_PIPELINE is not set — extraction would no-op.\n"
              "Run: ENABLE_KB_PIPELINE=1 python3 scripts/seed_demo.py",
              file=sys.stderr)
        return 1

    rc = 0
    for sid in DEMO_IDS:
        session = store.load_session(sid)
        if session is None:
            print(f"[skip] {sid}: not seeded (run alembic upgrade head; "
                  "fixture transcripts must be present)")
            rc = 1
            continue
        # v1 enrichment FIRST — the meeting detail page renders summary/
        # signals/entity-chips from `derived`, which 0009 seeds empty.
        # (Found by manual QA 2026-06-04: demo meeting pages were bare.)
        if not (session.derived and session.derived.summary):
            from transcripts.enrich import enrich_pending
            report = enrich_pending(session_id=sid)
            print(f"[enrich] {sid}: {report}")
        m = index_session(sid, with_headers=args.headers)
        if not m:
            print(f"[fail] {sid}: indexing failed")
            rc = 1
            continue
        print(f"[ok] {sid}: {m['chunks']} chunks, {m['embedded']} embedded")
        if not args.skip_extract:
            em = extract_session(sid)
            if em:
                print(f"     extracted: {em['entities']} entities, "
                      f"{em['inserted']} obligations")
            else:
                print(f"[warn] {sid}: extraction returned nothing")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
