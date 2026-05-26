"""
S1 tests — the closed tag taxonomy (skills/interview_reflection/taxonomy.py).

Pure data + normalization helpers, no LLM. Confirms the vocabulary loads, that
free-text tags map onto canonical tags (or to None when off-vocabulary), stage
ordering, and cross-pollinate adjacency.
"""
from __future__ import annotations

from skills.interview_reflection import taxonomy as tax


# --- vocabulary loads ---

def test_vocabularies_are_disjoint_and_populated():
    assert tax.DOMAINS and tax.SKILLS and tax.STAGES
    assert tax.DOMAINS.isdisjoint(tax.SKILLS)
    assert tax.ALL_TAGS == tax.DOMAINS | tax.SKILLS


# --- normalize_tag ---

def test_canonical_tag_passes_through():
    assert tax.normalize_tag("payments") == "payments"
    assert tax.normalize_tag("frontend") == "frontend"


def test_alias_maps_to_canonical():
    assert tax.normalize_tag("ML") == "ai-ml"
    assert tax.normalize_tag("ux") == "design-ux"
    assert tax.normalize_tag("sales") == "sales-bd"
    assert tax.normalize_tag("devtools") == "infra-devtools"


def test_whitespace_and_underscores_normalized():
    assert tax.normalize_tag("  Smart Contract ") == "smart-contracts"
    assert tax.normalize_tag("machine_learning") == "ai-ml"


def test_stage_is_recognized():
    assert tax.normalize_tag("early-traction") == "early-traction"


def test_off_vocabulary_returns_none():
    assert tax.normalize_tag("blockchain-quantum-thing") is None
    assert tax.normalize_tag("") is None
    assert tax.normalize_tag(None) is None  # type: ignore[arg-type]


# --- normalize_tags ---

def test_normalize_tags_maps_drops_and_dedupes():
    out = tax.normalize_tags(["ux", "UX", "frontend", "nonsense", "design"])
    # ux/UX/design all → design-ux (deduped); frontend kept; nonsense dropped
    assert out == ["design-ux", "frontend"]


def test_normalize_tags_handles_empty():
    assert tax.normalize_tags([]) == []
    assert tax.normalize_tags(None) == []  # type: ignore[arg-type]


# --- stage_index ---

def test_stage_index_order():
    assert tax.stage_index("idea") == 0
    assert tax.stage_index("scaling") == len(tax.STAGES) - 1
    assert tax.stage_index(None) is None
    assert tax.stage_index("not-a-stage") is None


# --- are_adjacent ---

def test_adjacent_within_group_but_different():
    assert tax.are_adjacent({"payments"}, {"defi"}) is True
    assert tax.are_adjacent({"ai-ml"}, {"data-analytics"}) is True


def test_identical_sets_are_not_adjacent():
    assert tax.are_adjacent({"payments"}, {"payments"}) is False


def test_unrelated_groups_not_adjacent():
    assert tax.are_adjacent({"payments"}, {"gaming"}) is False


def test_empty_sets_not_adjacent():
    assert tax.are_adjacent(set(), {"payments"}) is False
