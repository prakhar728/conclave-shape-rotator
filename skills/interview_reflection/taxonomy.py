"""
Closed tag vocabulary for the collaboration matching vertical.

The matcher's Step A (tag bucketing) is deterministic and explainable only if
tags come from a *closed set* fixed at extraction time. This module is that set
plus the helpers that normalize free-text LLM output back onto it. Anything the
vocabulary misses is recovered by the embedding rank (matcher Step B), so the
list is intentionally small and editable per cohort.

Source: collaboration_matching_vertical.md §3 (starter taxonomy v0).

Three vocabularies:
  - DOMAINS  — problem space ("what they're building in")
  - SKILLS   — capability ("what they can do")
  - STAGES   — ordered maturity ladder (proximity matters for peer matches)

`normalize_tag` is the only thing the agent layer calls: it lowercases,
hyphenates, maps a small alias table onto canonical tags, and returns None for
anything off-vocabulary (the agent then drops it). This keeps tag assignment
reproducible even though the LLM proposes the raw tags.
"""
from __future__ import annotations


# Problem space — "what are they building in".
DOMAINS: frozenset[str] = frozenset({
    "payments", "defi", "infra-devtools", "consumer-social", "ai-ml",
    "gaming", "security-privacy", "data-analytics", "marketplace", "fintech",
    "health", "climate", "crypto-protocol", "hardware",
})

# Capability — "what can they do / help with".
SKILLS: frozenset[str] = frozenset({
    "frontend", "backend", "smart-contracts", "ml-eng", "design-ux", "product",
    "growth-marketing", "sales-bd", "fundraising", "ops", "data-eng",
    "security-audit", "tokenomics", "research",
})

# Maturity ladder — ORDER MATTERS (peer matching uses stage proximity).
STAGES: tuple[str, ...] = (
    "idea", "prototype", "mvp-launched", "early-traction", "scaling",
)

# Domain + skill tags share one namespace for offers/needs/interests tagging.
ALL_TAGS: frozenset[str] = DOMAINS | SKILLS

# Common LLM phrasings → canonical tag. Kept deliberately small; the embedding
# rank covers anything not mapped here. Keys are pre-normalized (lowercased,
# spaces already hyphenated) — see _canon().
ALIASES: dict[str, str] = {
    "ml": "ai-ml",
    "ai": "ai-ml",
    "machine-learning": "ai-ml",
    "ml-engineering": "ml-eng",
    "mleng": "ml-eng",
    "devtools": "infra-devtools",
    "infra": "infra-devtools",
    "infrastructure": "infra-devtools",
    "developer-tools": "infra-devtools",
    "ux": "design-ux",
    "ui": "design-ux",
    "design": "design-ux",
    "sales": "sales-bd",
    "bd": "sales-bd",
    "business-development": "sales-bd",
    "growth": "growth-marketing",
    "marketing": "growth-marketing",
    "security": "security-privacy",
    "privacy": "security-privacy",
    "data": "data-analytics",
    "analytics": "data-analytics",
    "smart-contract": "smart-contracts",
    "contracts": "smart-contracts",
    "protocol": "crypto-protocol",
    "consumer": "consumer-social",
    "social": "consumer-social",
}

# Adjacency for cross-pollinate matches: tags in the same group are
# "related but different" — the seed for a serendipity intro. Membership is
# what `are_adjacent` checks; the embedding mid-band gate (matcher Step B)
# does the rest of the filtering.
DOMAIN_GROUPS: list[frozenset[str]] = [
    frozenset({"payments", "defi", "fintech"}),
    frozenset({"ai-ml", "data-analytics"}),
    frozenset({"infra-devtools", "crypto-protocol", "smart-contracts"}),
    frozenset({"consumer-social", "marketplace", "gaming"}),
    frozenset({"security-privacy", "crypto-protocol"}),
]


def _canon(raw: str) -> str:
    """Lowercase, strip, collapse whitespace/underscores to hyphens."""
    return "-".join(raw.strip().lower().replace("_", " ").split())


def normalize_tag(raw: str) -> str | None:
    """Map a free-text tag onto the closed vocabulary.

    Returns the canonical tag (a member of ALL_TAGS or STAGES) or None if the
    input is off-vocabulary. The agent layer drops None.
    """
    if not isinstance(raw, str) or not raw.strip():
        return None
    c = _canon(raw)
    c = ALIASES.get(c, c)
    if c in ALL_TAGS or c in STAGES:
        return c
    return None


def normalize_tags(raws: list[str]) -> list[str]:
    """Normalize a list of raw tags: map → drop None → dedupe, order-preserving."""
    out: list[str] = []
    seen: set[str] = set()
    for raw in raws or []:
        tag = normalize_tag(raw)
        if tag is not None and tag not in seen:
            seen.add(tag)
            out.append(tag)
    return out


def stage_index(stage: str | None) -> int | None:
    """Position of a stage on the maturity ladder, or None if unknown/None."""
    if stage in STAGES:
        return STAGES.index(stage)
    return None


def are_adjacent(tags_a: set[str], tags_b: set[str]) -> bool:
    """True if the two tag sets are related-but-different — they share a
    DOMAIN_GROUP but are not the same set. Used to seed cross-pollinate intros.
    """
    a, b = set(tags_a), set(tags_b)
    if not a or not b or a == b:
        return False
    for group in DOMAIN_GROUPS:
        if (a & group) and (b & group) and (a & group) != (b & group):
            return True
    return False
