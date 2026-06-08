#!/usr/bin/env python3
"""OI-1 diagnostic: is the dense leg pulling its weight vs FTS?  (LLM-free.)

Runs against the warm eval DB produced by score_retrieval.py (no re-ingest).
For each QMSum query computes FTS-only and dense-only NDCG@10 + recall@{10,50}
and reports three decision-relevant cuts:

  1. Win/loss/tie: on how many queries does dense beat FTS? (keep-vs-cut)
  2. Recall@50: does dense MISS relevant chunks, or just rank them lower?
     (a missing-recall problem and a ranking problem have different fixes)
  3. Complementarity: on queries where FTS is weak (NDCG<0.5), does dense
     rescue them? This is the real justification for a second leg even if
     dense loses on average.

Usage:
    CONCLAVE_DB_PATH=datasets/eval.db python3 scripts/eval/ablate_dense.py
"""
from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO = os.path.dirname(os.path.dirname(_HERE))
sys.path.insert(0, _REPO)
sys.path.insert(0, _HERE)

K = 10
FETCH = 50
EPS = 1e-6


def ndcg(rels: list[int], n_rel: int, k: int = K) -> float:
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rels[:k]))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(n_rel, k)))
    return dcg / ideal if ideal else 0.0


def recall_at(ranked: list[str], relevant: set[str], k: int) -> float:
    if not relevant:
        return 0.0
    return len(set(ranked[:k]) & relevant) / len(relevant)


def main() -> int:
    import ingest_harness as harness
    db = os.environ.get("CONCLAVE_DB_PATH", os.path.join(_REPO, "datasets", "eval.db"))
    harness.ensure_schema(db)

    import qmsum
    from storage import kb
    from transcripts.embed import embed_texts

    pairs = qmsum.load(domain="all", split="test")

    n = 0
    wins = losses = ties = 0
    margins = []                       # dense - fts ndcg, signed
    sum_fts_ndcg = sum_dense_ndcg = 0.0
    sum_fts_r10 = sum_dense_r10 = 0.0
    sum_fts_r50 = sum_dense_r50 = 0.0
    hard = []                          # (fts_ndcg, dense_ndcg) where fts < 0.5
    no_chunks = 0

    for meeting, queries in pairs:
        sid = meeting["session_id"]
        chunks = kb.query_chunks_for_session(sid)
        if not chunks:
            no_chunks += 1
            continue
        turns_by_chunk = {c["id"]: set(c["turn_ids"]) for c in chunks}
        for q in queries:
            rel_turns = q["relevant_turn_ids"]
            relevant = {cid for cid, t in turns_by_chunk.items() if t & rel_turns}
            if not relevant:
                continue
            fts = [h["chunk_id"] for h in
                   kb.fts_search_chunks(q["q"], limit=FETCH, session_ids=[sid])]
            qvec = embed_texts([q["q"]], kind="query")[0]
            dense = [h["chunk_id"] for h in
                     kb.vec_search_chunks(qvec, k=FETCH, session_ids=[sid])]

            f_ndcg = ndcg([1 if c in relevant else 0 for c in fts], len(relevant))
            d_ndcg = ndcg([1 if c in relevant else 0 for c in dense], len(relevant))
            n += 1
            margins.append(d_ndcg - f_ndcg)
            sum_fts_ndcg += f_ndcg
            sum_dense_ndcg += d_ndcg
            sum_fts_r10 += recall_at(fts, relevant, 10)
            sum_dense_r10 += recall_at(dense, relevant, 10)
            sum_fts_r50 += recall_at(fts, relevant, 50)
            sum_dense_r50 += recall_at(dense, relevant, 50)
            if d_ndcg > f_ndcg + EPS:
                wins += 1
            elif d_ndcg < f_ndcg - EPS:
                losses += 1
            else:
                ties += 1
            if f_ndcg < 0.5:
                hard.append((f_ndcg, d_ndcg))

    if no_chunks:
        print(f"[warn] {no_chunks} meetings had no chunks — run "
              f"score_retrieval.py first to warm the DB", file=sys.stderr)
    if not n:
        print("no scorable queries — is the eval DB indexed?", file=sys.stderr)
        return 1

    pct = lambda x: f"{100 * x / n:5.1f}%"
    print(f"\nDense-vs-FTS ablation over {n} QMSum queries (NDCG@{K}, recall@k)\n")
    print(f"  mean NDCG@{K}:    FTS {sum_fts_ndcg/n:.3f}   dense {sum_dense_ndcg/n:.3f}")
    print(f"  mean recall@10:  FTS {sum_fts_r10/n:.3f}   dense {sum_dense_r10/n:.3f}")
    print(f"  mean recall@50:  FTS {sum_fts_r50/n:.3f}   dense {sum_dense_r50/n:.3f}")
    print(f"\n  dense WINS:  {wins:4d}  ({pct(wins)})")
    print(f"  dense LOSES: {losses:4d}  ({pct(losses)})")
    print(f"  TIES:        {ties:4d}  ({pct(ties)})")
    dense_win_margins = [m for m in margins if m > EPS]
    dense_loss_margins = [-m for m in margins if m < -EPS]
    if dense_win_margins:
        print(f"  avg margin when dense wins:  +{sum(dense_win_margins)/len(dense_win_margins):.3f}")
    if dense_loss_margins:
        print(f"  avg margin when dense loses: -{sum(dense_loss_margins)/len(dense_loss_margins):.3f}")

    # Complementarity: where FTS is weak, does dense rescue?
    if hard:
        rescued = sum(1 for f, d in hard if d > f + EPS)
        big_rescue = sum(1 for f, d in hard if d - f > 0.3)
        mean_d_on_hard = sum(d for _, d in hard) / len(hard)
        print(f"\n  Complementarity — {len(hard)} 'hard' queries (FTS NDCG<0.5):")
        print(f"    dense beats FTS on:        {rescued} ({100*rescued/len(hard):.0f}%)")
        print(f"    dense rescues big (+0.3):  {big_rescue} ({100*big_rescue/len(hard):.0f}%)")
        print(f"    mean dense NDCG on hard:   {mean_d_on_hard:.3f}")

    print("\nReading: dense MISSING recall (low recall@50) => model/index "
          "problem; dense recall OK but low NDCG => ranking problem; high "
          "rescue% on hard queries => keep dense despite avg loss.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
