"""Q1 bake-off scoring: predictions vs Codex-labelled ground truth (C3).

Matching is fuzzy by necessity — an extractor's phrasing never equals the
labeller's. Match score between a predicted and gold item combines
description text similarity with turn-id overlap; a greedy one-to-one
assignment above threshold counts as a true positive.

Methodology caveat (recorded in transcripts/EVAL.md at C4): ground truth
is Codex-generated (see fixtures LABELER_PROMPT.md), so F1 here measures
agreement-with-Codex. The Q1 one-prompt vs per-type comparison is sound
(both graded against the same truth); absolute numbers are not accuracy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from transcripts.extract_bakeoff import (
    ENTITY_TYPES,
    OBLIGATION_TYPES,
    token_set_ratio,
)

#: Minimum combined score for a pred/gold obligation pair to count as a match.
OBLIGATION_MATCH_THRESHOLD = 0.35
#: Weights: descriptions matter more than turn overlap (turn ids are noisy
#: on both sides — chunk overlap, labeller judgment).
W_TEXT = 0.7
W_TURNS = 0.3
#: Entity name similarity floor.
ENTITY_MATCH_THRESHOLD = 0.5


# ---------------------------------------------------------------------------
# Pair scoring
# ---------------------------------------------------------------------------

def turn_overlap(a: list[int], b: list[int]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def obligation_pair_score(pred: dict, gold: dict) -> float:
    text = token_set_ratio(pred.get("description") or "", gold.get("description") or "")
    turns = turn_overlap(pred.get("turn_ids") or [], gold.get("turn_ids") or [])
    return W_TEXT * text + W_TURNS * turns


def entity_pair_score(pred: dict, gold: dict) -> float:
    """Max similarity across canonical names and all surface forms."""
    pred_names = [pred.get("canonical_name") or ""] + list(pred.get("raw_mentions") or [])
    gold_names = [gold.get("canonical_name") or ""] + list(gold.get("raw_mentions") or [])
    best = 0.0
    for p in pred_names:
        for g in gold_names:
            if not p or not g:
                continue
            pc, gc = p.casefold().strip(), g.casefold().strip()
            if pc == gc:
                return 1.0
            # containment ("Andrew" in "Andrew Miller") counts strongly
            if pc in gc or gc in pc:
                best = max(best, 0.9)
            best = max(best, token_set_ratio(p, g))
    return best


# ---------------------------------------------------------------------------
# Greedy one-to-one matching
# ---------------------------------------------------------------------------

def greedy_match(
    preds: list[dict],
    golds: list[dict],
    score_fn,
    threshold: float,
) -> list[tuple[int, int, float]]:
    """Highest-scoring pairs first, each pred/gold used at most once."""
    scored = []
    for i, p in enumerate(preds):
        for j, g in enumerate(golds):
            s = score_fn(p, g)
            if s >= threshold:
                scored.append((s, i, j))
    scored.sort(reverse=True)
    used_p: set[int] = set()
    used_g: set[int] = set()
    matches = []
    for s, i, j in scored:
        if i in used_p or j in used_g:
            continue
        used_p.add(i)
        used_g.add(j)
        matches.append((i, j, s))
    return matches


# ---------------------------------------------------------------------------
# F1
# ---------------------------------------------------------------------------

@dataclass
class PRF:
    tp: int = 0
    fp: int = 0
    fn: int = 0

    @property
    def precision(self) -> float:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else 0.0

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if (p + r) else 0.0

    def add(self, other: "PRF") -> None:
        self.tp += other.tp
        self.fp += other.fp
        self.fn += other.fn


@dataclass
class BakeoffScore:
    """Per-transcript, per-strategy scores."""
    obligations_by_type: dict[str, PRF] = field(default_factory=dict)
    obligations_type_agnostic: PRF = field(default_factory=PRF)
    entities_overall: PRF = field(default_factory=PRF)

    @property
    def obligation_macro_f1(self) -> float:
        """Mean F1 over obligation types that have gold support."""
        scored = [
            prf.f1 for prf in self.obligations_by_type.values()
            if (prf.tp + prf.fn) > 0  # gold has at least one of this type
        ]
        return sum(scored) / len(scored) if scored else 0.0


def score_obligations(preds: list[dict], golds: list[dict]) -> BakeoffScore:
    out = BakeoffScore()
    # Per-type: match within same-type buckets only.
    for otype in OBLIGATION_TYPES:
        p = [x for x in preds if x.get("type") == otype]
        g = [x for x in golds if x.get("type") == otype]
        m = greedy_match(p, g, obligation_pair_score, OBLIGATION_MATCH_THRESHOLD)
        out.obligations_by_type[otype] = PRF(tp=len(m), fp=len(p) - len(m), fn=len(g) - len(m))
    # Type-agnostic: how much is pure type-confusion costing?
    m = greedy_match(preds, golds, obligation_pair_score, OBLIGATION_MATCH_THRESHOLD)
    out.obligations_type_agnostic = PRF(tp=len(m), fp=len(preds) - len(m), fn=len(golds) - len(m))
    return out


def score_entities(preds: list[dict], golds: list[dict]) -> PRF:
    """Type-agnostic entity matching (type confusion between project/tool/
    topic is endemic on both sides; name identity is the real signal)."""
    m = greedy_match(preds, golds, entity_pair_score, ENTITY_MATCH_THRESHOLD)
    return PRF(tp=len(m), fp=len(preds) - len(m), fn=len(golds) - len(m))


def score_transcript(pred: dict, gold: dict) -> BakeoffScore:
    s = score_obligations(pred.get("obligations") or [], gold.get("obligations") or [])
    s.entities_overall = score_entities(pred.get("entities") or [], gold.get("entities") or [])
    return s


# ---------------------------------------------------------------------------
# Report rendering
# ---------------------------------------------------------------------------

def render_report(
    results: dict[str, dict[str, BakeoffScore]],
    *,
    model_id: str,
    notes: Optional[str] = None,
) -> str:
    """``results[transcript_slug][strategy] -> BakeoffScore`` → markdown.

    Strategies are expected to be 'one_prompt' and 'per_type'.
    """
    lines = [
        "# Q1 bake-off results — one-prompt vs per-type extraction",
        "",
        f"Model: `{model_id}`. Scoring: greedy one-to-one fuzzy match "
        f"(text {W_TEXT} / turn-overlap {W_TURNS}, threshold "
        f"{OBLIGATION_MATCH_THRESHOLD}); entities matched type-agnostically "
        f"by name similarity (threshold {ENTITY_MATCH_THRESHOLD}).",
        "",
        "Ground truth: Codex-labelled (see LABELER_PROMPT.md). F1 here is "
        "agreement-with-Codex; the one_prompt vs per_type comparison is the "
        "decision signal, not the absolute numbers.",
        "",
    ]
    if notes:
        lines += [notes, ""]

    # Aggregates across transcripts
    agg: dict[str, BakeoffScore] = {}
    for slug, by_strategy in results.items():
        for strategy, score in by_strategy.items():
            tgt = agg.setdefault(strategy, BakeoffScore())
            for otype, prf in score.obligations_by_type.items():
                tgt.obligations_by_type.setdefault(otype, PRF()).add(prf)
            tgt.obligations_type_agnostic.add(score.obligations_type_agnostic)
            tgt.entities_overall.add(score.entities_overall)

    lines.append("## Aggregate (all transcripts pooled)")
    lines.append("")
    lines.append("| metric | " + " | ".join(sorted(agg)) + " |")
    lines.append("|---|" + "---|" * len(agg))
    strategies = sorted(agg)
    for otype in OBLIGATION_TYPES:
        row = [f"obligation F1: {otype}"]
        for s in strategies:
            prf = agg[s].obligations_by_type.get(otype, PRF())
            support = prf.tp + prf.fn
            row.append(f"{prf.f1:.2f} (n={support})")
        lines.append("| " + " | ".join(row) + " |")
    row = ["obligation macro-F1"]
    for s in strategies:
        row.append(f"{agg[s].obligation_macro_f1:.2f}")
    lines.append("| " + " | ".join(row) + " |")
    row = ["obligation F1 (type-agnostic)"]
    for s in strategies:
        row.append(f"{agg[s].obligations_type_agnostic.f1:.2f}")
    lines.append("| " + " | ".join(row) + " |")
    row = ["entity F1"]
    for s in strategies:
        row.append(f"{agg[s].entities_overall.f1:.2f}")
    lines.append("| " + " | ".join(row) + " |")
    lines.append("")

    for slug, by_strategy in sorted(results.items()):
        lines.append(f"## {slug}")
        lines.append("")
        strategies = sorted(by_strategy)
        lines.append("| metric | " + " | ".join(strategies) + " |")
        lines.append("|---|" + "---|" * len(strategies))
        for otype in OBLIGATION_TYPES:
            row = [f"obligation F1: {otype}"]
            for s in strategies:
                prf = by_strategy[s].obligations_by_type.get(otype, PRF())
                support = prf.tp + prf.fn
                row.append(f"{prf.f1:.2f} (n={support})")
            lines.append("| " + " | ".join(row) + " |")
        row = ["obligation macro-F1"]
        for s in strategies:
            row.append(f"{by_strategy[s].obligation_macro_f1:.2f}")
        lines.append("| " + " | ".join(row) + " |")
        row = ["entity F1"]
        for s in strategies:
            row.append(f"{by_strategy[s].entities_overall.f1:.2f}")
        lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    return "\n".join(lines)
