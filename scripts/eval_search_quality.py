#!/usr/bin/env python3
"""NDCG@10 over the C2 eval queries against the live hybrid index (C24).

Runs the 28 ground-truth queries (tests/fixtures/transcripts/
*.expected.yaml `queries:` sections) through the same primitives the
search endpoint uses (FTS5 + sqlite-vec + RRF), computes NDCG@10 per
query, and prints per-transcript + overall means.

Relevance: binary at chunk level — a retrieved chunk is relevant iff
its turn_ids intersect the query's gold relevant_turn_ids. Retrieval
is restricted to the query's own session (the gold labels are
per-transcript; cross-session noise would mismeasure the ranker).

Usage:
    python3 scripts/eval_search_quality.py [--k 10] [--no-vec | --no-fts]

Append the resulting numbers to transcripts/EVAL.md (C24/C25 decision
records) — this script prints, it does not write.
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import yaml  # noqa: E402

FIXTURE_DIR = REPO / "tests" / "fixtures" / "transcripts"

#: fixture slug → session id in the live DB (cohort sessions are the
#: same transcripts; slugs differ because store derives them from
#: filenames at ingest).
SESSION_BY_SLUG = {
    "elocute": "elocute-transcript-may-26",
    "dstack-intro-salon": "dstack-intro-salon-session-transcript-may-20",
    "project-intros-agents-day3": "project-intros-agents-day-3-transcript-may-21",
}


def ndcg_at_k(ranked_relevance: list[int], n_relevant: int, k: int) -> float:
    """Binary-relevance NDCG@k."""
    dcg = sum(
        rel / math.log2(i + 2) for i, rel in enumerate(ranked_relevance[:k])
    )
    ideal = sum(1 / math.log2(i + 2) for i in range(min(n_relevant, k)))
    return dcg / ideal if ideal > 0 else 0.0


def run_query(query: str, session_id: str, *, k: int, use_fts: bool, use_vec: bool):
    from infra.rrf import rrf_fuse
    from storage import kb

    lists = []
    if use_fts:
        hits = kb.fts_search_chunks(query, limit=50, session_ids=[session_id])
        lists.append([h["chunk_id"] for h in hits])
    if use_vec:
        try:
            from transcripts.embed import embed_texts
            qvec = embed_texts([query], kind="query")[0]
            hits = kb.vec_search_chunks(qvec, k=50, session_ids=[session_id])
            lists.append([h["chunk_id"] for h in hits])
        except Exception as exc:  # noqa: BLE001
            print(f"  [warn] vec leg failed: {exc}", file=sys.stderr)
    return [cid for cid, _ in rrf_fuse(lists)][:k]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--no-vec", action="store_true")
    ap.add_argument("--no-fts", action="store_true")
    args = ap.parse_args()

    from storage import kb

    overall: list[float] = []
    for slug, session_id in SESSION_BY_SLUG.items():
        gold = yaml.safe_load(open(FIXTURE_DIR / f"{slug}.expected.yaml"))
        chunks = kb.query_chunks_for_session(session_id)
        if not chunks:
            print(f"{slug}: session {session_id} has no chunks — run backfill first")
            continue
        turns_by_chunk = {c["id"]: set(c["turn_ids"]) for c in chunks}

        scores = []
        for q in gold.get("queries") or []:
            rel_turns = set(q["relevant_turn_ids"])
            relevant_chunks = {
                cid for cid, turns in turns_by_chunk.items() if turns & rel_turns
            }
            if not relevant_chunks:
                continue  # gold turns fell outside any chunk (shouldn't happen)
            ranked = run_query(
                q["q"], session_id, k=args.k,
                use_fts=not args.no_fts, use_vec=not args.no_vec,
            )
            rels = [1 if cid in relevant_chunks else 0 for cid in ranked]
            s = ndcg_at_k(rels, len(relevant_chunks), args.k)
            scores.append(s)

        mean = sum(scores) / len(scores) if scores else 0.0
        overall.extend(scores)
        print(f"{slug:<32} n={len(scores):>2}  NDCG@{args.k} = {mean:.3f}")

    if overall:
        print(f"\n{'OVERALL':<32} n={len(overall):>2}  NDCG@{args.k} = "
              f"{sum(overall) / len(overall):.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
