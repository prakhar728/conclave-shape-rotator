"""Reciprocal Rank Fusion (Phase 3.5c C23).

Generic RRF over any number of ranked lists (Cormack et al. 2009):

    score(d) = Σ_lists 1 / (k + rank_d)

k=60 is the canonical constant (Survey D7); it damps the head so a
document ranked #1 in one list and absent in another doesn't dominate
a document ranked #3 in both.
"""
from __future__ import annotations

from typing import Hashable, Iterable

RRF_K = 60


def rrf_fuse(
    ranked_lists: Iterable[Iterable[Hashable]],
    *,
    k: int = RRF_K,
) -> list[tuple[Hashable, float]]:
    """Fuse ranked id lists → [(id, score)] best-first.

    Each input list is best-first; rank is 1-based position. Ids absent
    from a list simply contribute nothing for it.
    """
    scores: dict[Hashable, float] = {}
    for lst in ranked_lists:
        for rank, doc_id in enumerate(lst, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda t: (-t[1], str(t[0])))
