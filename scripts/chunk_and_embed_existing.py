#!/usr/bin/env python3
"""Backfill KB indexing (chunks + FTS + embeddings) for existing sessions.

Phase 3.5a C11. Idempotent: ``index_session`` replaces chunks per
session and upserts embeddings, so re-running is always safe.

Usage:
    python3 scripts/chunk_and_embed_existing.py [--headers] [--only SESSION_ID]
        [--skip-indexed] [--dry-run]

Defaults to NO context headers (each header is an LLM call against the
configured backend — on redpill that's a paid API hit per chunk). Run a
second pass with --headers when you want them; embedding text changes,
so embeddings are recomputed for headered sessions.

--skip-indexed skips sessions that already have chunks — the fast
nightly-cron mode. Without it every session is re-indexed.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--headers", action="store_true",
                    help="generate per-chunk context headers (LLM call per chunk)")
    ap.add_argument("--only", default=None, help="backfill a single session id")
    ap.add_argument("--skip-indexed", action="store_true",
                    help="skip sessions that already have chunks")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    from transcripts import store
    from transcripts.kb_pipeline import index_session
    from storage import kb

    sessions = store.list_sessions()
    ids = [s.session_id for s in sessions]
    if args.only:
        if args.only not in ids:
            print(f"unknown session {args.only!r}", file=sys.stderr)
            return 1
        ids = [args.only]

    done = skipped = failed = 0
    for sid in ids:
        if args.skip_indexed and kb.query_chunks_for_session(sid):
            skipped += 1
            continue
        if args.dry_run:
            print(f"[dry-run] would index {sid}")
            done += 1
            continue
        metrics = index_session(sid, with_headers=args.headers)
        if metrics is None:
            print(f"[skip] {sid}: no segments / not found")
            skipped += 1
            continue
        ok = metrics["embedded"] == metrics["chunks"]
        status = "ok" if ok else "fts-only"
        print(f"[{status}] {sid}: {metrics['chunks']} chunks, "
              f"{metrics['embedded']} embedded, {metrics['ms_total']}ms")
        done += 1
        if not ok:
            failed += 1

    print(f"\nbackfill: {done} indexed, {skipped} skipped, "
          f"{failed} with embedding failures (FTS still searchable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
