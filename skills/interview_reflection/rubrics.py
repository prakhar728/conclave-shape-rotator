"""
The five frozen personality instruments + deterministic aggregation.

Source: instrument_registry_v0.md. These items ARE the determinism-critical
content: the rubric node asks the LLM to score the SAME fixed items (scale point
+ verbatim quote) every time; this module then maps items → rubric scores in
PURE CODE (no model in the aggregation path).

Universal rules (instrument_registry_v0.md):
  - Scale 1–5. A non-null score MUST carry a verbatim evidence quote, else the
    item does not count (never guessed).
  - A rubric reports a score only if a minimum number of its items count;
    otherwise it is "insufficient evidence this session" (reported=False) — a
    feature, not a failure.
  - PG3 (cross-source corroboration) is fusion-only: it is null until an
    observed source (commits/artifacts) is bound. v1 binds none, so PG3 is
    always nulled here and excluded from the progress minimum; its contradiction
    flag stays None.
"""
from __future__ import annotations

from skills.interview_reflection.models import RubricItem, RubricPanel, RubricScore


# id → (factor, question, anchor@1, anchor@3, anchor@5)
ITEM_DEFS: dict[str, dict[str, str]] = {
    # SOFT-1 Coachability
    "CO1": {"factor": "openness", "q": "Response to a concern/correction?",
            "a1": "Dismisses / defensive", "a3": "Acknowledges, doesn't engage substance",
            "a5": "Engages, asks follow-ups, updates"},
    "CO2": {"factor": "vulnerability", "q": "Surfaces something they got wrong, unprompted?",
            "a1": "Only wins", "a3": "Admits when asked", "a5": "Proactively names failure/blocker"},
    "CO3": {"factor": "awareness", "q": "Accurately identifies own limitations?",
            "a1": "None / externalized", "a3": "Generic / vague", "a5": "Specific, owned, situated"},
    "CO4": {"factor": "growth", "q": "Changed behavior from past feedback? (longitudinal)",
            "a1": "None / repeats pattern", "a3": "Intends to, no action", "a5": "Concrete change + result"},
    "CO5": {"factor": "external support", "q": "Actively pulls on mentors/peers/users?",
            "a1": "Solo", "a3": "Input passively received", "a5": "Actively solicits + applies"},
    # SOFT-2 Agency / Locus of control
    "LC1": {"factor": "internality", "q": "Where does the person locate the cause of a setback?",
            "a1": "External / uncontrollable (market, cofounder, tools, luck)", "a3": "Mixed",
            "a5": "Owns controllable cause + what they'd do differently"},
    "LC2": {"factor": "stability/globality", "q": "Setbacks framed as permanent/global or temporary/specific?",
            "a1": "Permanent, global ('we just can't')", "a3": "Mixed",
            "a5": "Temporary, specific ('this slipped because X')"},
    "LC3": {"factor": "—", "q": "Posture under constraint",
            "a1": "Describes feeling stuck", "a3": "Acknowledges options",
            "a5": "Names a concrete lever they control"},
    # SOFT-3 Proactivity
    "PR1": {"factor": "self-initiation", "q": "Self-initiation",
            "a1": "Waits for direction", "a3": "Acts when prompted", "a5": "Starts things unprompted"},
    "PR2": {"factor": "opportunity scanning", "q": "Opportunity scanning",
            "a1": "Reactive to problems", "a3": "Notices, doesn't act", "a5": "Anticipates + acts ahead"},
    "PR3": {"factor": "perseverance", "q": "Perseverance",
            "a1": "Drops it when blocked", "a3": "Pushes once", "a5": "Persists via alternative approaches"},
    # HARD-1 Goal commitment
    "GC1": {"factor": "goal specificity", "q": "Goal specificity",
            "a1": "Vague aspiration", "a3": "Directional", "a5": "Specific, measurable, time-bound"},
    "GC2": {"factor": "commitment language", "q": "Commitment language",
            "a1": "Hedges / already discounting", "a3": "Conditional", "a5": "Firm determination"},
    "GC3": {"factor": "goal stability", "q": "Goal stability (longitudinal)",
            "a1": "Abandons silently", "a3": "Revises with rationale", "a5": "Maintains / deliberately re-commits"},
    "GC4": {"factor": "difficulty calibration", "q": "Difficulty calibration",
            "a1": "Trivial or fantasy", "a3": "Reasonable", "a5": "Stretch-but-achievable"},
    # HARD-2 Progress
    "PG1": {"factor": "concrete output", "q": "Concrete output",
            "a1": "Busy, no output", "a3": "Some output", "a5": "Specific completed deliverables"},
    "PG2": {"factor": "progress vs stated goals", "q": "Progress vs stated goals",
            "a1": "Orthogonal drift", "a3": "Partially on-track", "a5": "Directly advances stated goals"},
    "PG3": {"factor": "cross-source corroboration", "q": "Cross-source corroboration (fusion; null if no source)",
            "a1": "Stated >> observed (contradiction)", "a3": "Partial match", "a5": "Stated matches commits/artifacts"},
    "PG4": {"factor": "setback handling", "q": "Setback handling",
            "a1": "Stall unexamined", "a3": "Acknowledged", "a5": "Diagnosed cause + recovery plan"},
}

# rubric key → {name, min items to report, ordered item ids}
RUBRIC_REGISTRY: dict[str, dict] = {
    "coachability":    {"name": "Coachability", "min": 3, "items": ["CO1", "CO2", "CO3", "CO4", "CO5"]},
    "agency":          {"name": "Agency / Locus of control", "min": 2, "items": ["LC1", "LC2", "LC3"]},
    "proactivity":     {"name": "Proactivity", "min": 2, "items": ["PR1", "PR2", "PR3"]},
    "goal_commitment": {"name": "Goal commitment", "min": 3, "items": ["GC1", "GC2", "GC3", "GC4"]},
    "progress":        {"name": "Progress", "min": 2, "items": ["PG1", "PG2", "PG3", "PG4"]},
}

# Items that require a bound observed source; nulled (and excluded from the
# rubric minimum) until that source is wired. v1 binds none.
FUSION_ITEMS: frozenset[str] = frozenset({"PG3"})


def _band(mean: float) -> str:
    if mean < 2.5:
        return "low"
    if mean >= 4.0:
        return "strong"
    return "mixed"


def _coerce_score(raw) -> int | None:
    if isinstance(raw, bool):
        return None
    if isinstance(raw, (int, float)) and 1 <= raw <= 5:
        return int(round(raw))
    return None


def aggregate_panel(raw_items: dict) -> RubricPanel:
    """Map raw LLM item output → RubricPanel. Pure code.

    raw_items: {"CO1": {"score": int|None, "quote": str|None}, ...}. Missing or
    malformed entries are treated as null. A score counts toward a rubric only
    if it is 1..5 AND carries a non-empty quote.
    """
    if not isinstance(raw_items, dict):
        raw_items = {}

    scores: dict[str, RubricScore] = {}
    for key, spec in RUBRIC_REGISTRY.items():
        items: list[RubricItem] = []
        counting: list[int] = []
        for item_id in spec["items"]:
            entry = raw_items.get(item_id) if isinstance(raw_items.get(item_id), dict) else {}
            quote = entry.get("quote")
            quote = quote.strip() if isinstance(quote, str) and quote.strip() else None
            score = _coerce_score(entry.get("score"))

            if item_id in FUSION_ITEMS:
                # No observed source bound in v1 → force null, no contradiction.
                items.append(RubricItem(id=item_id, score=None, quote=None))
                continue

            # Quote-anchoring: a score without a quote does not count.
            if score is not None and quote is not None:
                items.append(RubricItem(id=item_id, score=score, quote=quote))
                counting.append(score)
            else:
                items.append(RubricItem(id=item_id, score=None, quote=quote))

        reported = len(counting) >= spec["min"]
        mean = round(sum(counting) / len(counting), 2) if counting else None
        scores[key] = RubricScore(
            rubric=spec["name"],
            score=mean if reported else None,
            band=_band(mean) if (reported and mean is not None) else None,
            reported=reported,
            items=items,
            contradiction_flag=None,   # PG3 fusion source not bound in v1
        )

    return RubricPanel(**scores)


def format_items_for_prompt() -> str:
    """Render all 19 items as `ID — question | 1: a1 / 3: a3 / 5: a5` lines."""
    lines = []
    for key, spec in RUBRIC_REGISTRY.items():
        lines.append(f"[{spec['name']}]")
        for item_id in spec["items"]:
            d = ITEM_DEFS[item_id]
            lines.append(f"  {item_id} — {d['q']} | 1: {d['a1']} / 3: {d['a3']} / 5: {d['a5']}")
    return "\n".join(lines)
