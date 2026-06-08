#!/usr/bin/env python3
"""Held-out retrieval eval: QMSum NDCG@10 through the real pipeline (Phase 1a).

Ingests QMSum meetings via the shared eval ingest harness (the production
seam) and scores NDCG@k of FTS-only / dense-only / hybrid retrieval against
QMSum's human-annotated ``relevant_text_span`` labels.

Methodology mirrors ``scripts/eval_search_quality.py`` so numbers are
comparable to the in-sample 0.814 baseline in ``transcripts/EVAL.md``:
binary chunk relevance (chunk is relevant iff its ``turn_ids`` intersect the
query's gold turn ids), retrieval scoped to the query's own meeting. The
difference that matters: these queries are human-written and paraphrase-style
(e.g. "Summarize the discussion about microphone issues"), not Codex-written
quotes of transcript vocabulary — so this is the honest, held-out number.

Usage::

    CONCLAVE_DB_PATH=datasets/eval.db \\
      python3 scripts/eval/score_retrieval.py \\
        [--domain all|Academic|Committee|Product] [--split test] \\
        [--k 10] [--limit N] [--headers] [--no-reingest]
"""
from __future__ import annotations

import argparse
import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _REPO)
sys.path.insert(0, _HERE)

LEGS = ("fts", "dense", "hybrid")


def ndcg_at_k(ranked_relevance: list[int], n_relevant: int, k: int) -> float:
    """Binary-relevance NDCG@k."""
    dcg = sum(rel / math.log2(i + 2) for i, rel in enumerate(ranked_relevance[:k]))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(n_relevant, k)))
    return dcg / ideal if ideal > 0 else 0.0


def _rank_all_legs(query: str, sid: str, *, fetch: int, dense_ok: bool):
    """Return {leg: [chunk_id ranked]} computing the query embedding once."""
    from infra.rrf import rrf_fuse
    from storage import kb

    fts = [h["chunk_id"] for h in
           kb.fts_search_chunks(query, limit=fetch, session_ids=[sid])]
    out = {"fts": fts, "dense": [], "hybrid": fts}
    if not dense_ok:
        return out
    try:
        from transcripts.embed import embed_texts
        qvec = embed_texts([query], kind="query")[0]
        vec = [h["chunk_id"] for h in
               kb.vec_search_chunks(qvec, k=fetch, session_ids=[sid])]
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] dense leg unavailable: {exc}", file=sys.stderr)
        return out
    out["dense"] = vec
    out["hybrid"] = [cid for cid, _ in rrf_fuse([fts, vec])]
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--domain", default="all",
                    choices=["all", "Academic", "Committee", "Product"])
    ap.add_argument("--split", default="test")
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None,
                    help="cap meetings per domain (logged); default all")
    ap.add_argument("--headers", action="store_true",
                    help="generate context headers at ingest (LLM cost; "
                         "production default). Off = comparable to 0.814.")
    ap.add_argument("--no-reingest", action="store_true",
                    help="skip ingest; score against an already-indexed DB")
    ap.add_argument("--db", default=os.environ.get("CONCLAVE_DB_PATH",
                    os.path.join(_REPO, "datasets", "eval.db")))
    args = ap.parse_args()

    import ingest_harness as harness

    harness.ensure_schema(args.db)
    from storage import kb
    from storage.sqlite import _get_conn
    from storage.vec import vec_available

    dense_ok = vec_available(_get_conn())
    if not dense_ok:
        print("[warn] sqlite-vec not loaded — dense/hybrid will be empty",
              file=sys.stderr)

    import qmsum
    pairs = qmsum.load(domain=args.domain, split=args.split)

    # Cap per domain (logged, no silent truncation).
    if args.limit is not None:
        capped: list = []
        seen: dict[str, int] = {}
        for meeting, queries in pairs:
            d = meeting["domain"]
            if seen.get(d, 0) >= args.limit:
                continue
            seen[d] = seen.get(d, 0) + 1
            capped.append((meeting, queries))
        dropped = len(pairs) - len(capped)
        print(f"[cap] --limit {args.limit}/domain: keeping {len(capped)} "
              f"meetings, dropping {dropped}")
        pairs = capped

    n_q = sum(len(q) for _, q in pairs)
    print(f"QMSum {args.split} / domain={args.domain}: "
          f"{len(pairs)} meetings, {n_q} scorable queries "
          f"(headers={'on' if args.headers else 'off'}, dense={'on' if dense_ok else 'off'})")

    if not args.no_reingest:
        print("Ingesting through production seam (store.save_session -> index_session)...")
        harness.ingest_corpus([m for m, _ in pairs], with_headers=args.headers)

    # Score: per-domain and overall accumulators, per leg.
    from collections import defaultdict
    scores: dict[str, dict[str, list[float]]] = defaultdict(
        lambda: {leg: [] for leg in LEGS})
    fetch = max(args.k * 5, 50)

    for meeting, queries in pairs:
        sid = meeting["session_id"]
        dom = meeting["domain"]
        chunks = kb.query_chunks_for_session(sid)
        if not chunks:
            print(f"  [warn] {sid}: no chunks indexed — skipping", file=sys.stderr)
            continue
        turns_by_chunk = {c["id"]: set(c["turn_ids"]) for c in chunks}
        for q in queries:
            rel_turns = q["relevant_turn_ids"]
            relevant = {cid for cid, turns in turns_by_chunk.items()
                        if turns & rel_turns}
            if not relevant:
                continue  # gold turns fell outside every chunk (shouldn't happen)
            ranked = _rank_all_legs(q["q"], sid, fetch=fetch, dense_ok=dense_ok)
            for leg in LEGS:
                rels = [1 if cid in relevant else 0 for cid in ranked[leg][:args.k]]
                scores[dom][leg].append(ndcg_at_k(rels, len(relevant), args.k))

    # Report.
    def _mean(xs: list[float]) -> float:
        return sum(xs) / len(xs) if xs else 0.0

    doms = sorted(scores.keys())
    print(f"\n{'domain':<14}{'n':>5}   " + "  ".join(f"{leg:>8}" for leg in LEGS))
    print("-" * 52)
    overall = {leg: [] for leg in LEGS}
    for dom in doms:
        n = len(scores[dom]["fts"])
        cells = "  ".join(f"{_mean(scores[dom][leg]):>8.3f}" for leg in LEGS)
        print(f"{dom:<14}{n:>5}   {cells}")
        for leg in LEGS:
            overall[leg].extend(scores[dom][leg])
    n_all = len(overall["fts"])
    cells = "  ".join(f"{_mean(overall[leg]):>8.3f}" for leg in LEGS)
    print("-" * 52)
    print(f"{'OVERALL':<14}{n_all:>5}   {cells}")
    print(f"\nNDCG@{args.k}. In-sample baseline (transcripts/EVAL.md C24): "
          f"hybrid 0.814 / FTS 0.835 / dense 0.693 on 28 Codex-written queries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
