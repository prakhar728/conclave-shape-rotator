#!/usr/bin/env python3
"""Task #40 — backfill short meeting titles for legacy sessions.

Sessions enriched before the title field existed have a `summary` but no
`derived.title`. This generates a title from the *existing* summary (one cheap
LLM call per session — no full re-enrich) and persists it. Idempotent: sessions
that already have a title, an owner rename (`metadata.manual_title`), or no
summary are skipped.

Writes directly to the Conclave DB (CONCLAVE_DB_PATH); no running server needed.
Run with --dry-run to preview counts without writing.

    python scripts/backfill_titles.py [--dry-run] [--limit N]
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # repo root on path


def _needs_title(session) -> bool:
    d = session.derived
    if not (d and d.summary):
        return False  # nothing to base a title on
    if session.metadata.manual_title:
        return False  # owner already named it
    return not d.title


def main() -> int:
    ap = argparse.ArgumentParser(description="Backfill meeting titles from summaries.")
    ap.add_argument("--dry-run", action="store_true", help="Count only; do not write.")
    ap.add_argument("--limit", type=int, default=0, help="Cap sessions processed (0 = all).")
    args = ap.parse_args()

    from transcripts import store
    from transcripts.enrich import _generate_title

    sessions = store.list_sessions()
    todo = [s for s in sessions if _needs_title(s)]
    if args.limit:
        todo = todo[: args.limit]

    print(f"{len(todo)} session(s) need a title (of {len(sessions)} total).")
    filled = 0
    for s in todo:
        title = _generate_title(s.derived.summary, llm=None, model=None)
        if not title:
            print(f"  - {s.session_id}: title generation returned nothing (skipped)")
            continue
        print(f"  - {s.session_id}: {title!r}")
        if not args.dry_run:
            s.derived.title = title
            store.set_derived(s.session_id, s.derived)
            filled += 1

    if args.dry_run:
        print("dry-run: no titles written.")
    else:
        print(f"backfilled {filled} title(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
