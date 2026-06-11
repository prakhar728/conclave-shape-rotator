"""Commit 2 (OI-7 fix) — entity `definition` + person `role` cleaning/merge.

Pure unit tests on `_clean_entities` + `merge_entities` (no LLM/network): the new
additive fields are parsed, the role enum is coerced, and both fields consolidate
correctly across chunks. Backward-compat: rows without the fields still merge.
"""
from __future__ import annotations

from transcripts.extract import _clean_entities, merge_entities


def test_clean_entity_parses_definition_and_person_role():
    rows = [
        {"type": "person", "canonical_name": "Andrew Miller", "role": "Researcher",
         "definition": "  a security researcher on the team  ",
         "raw_mentions": ["Andrew"], "turn_ids": [1]},
        {"type": "tool", "canonical_name": "DStack",
         "definition": "a confidential-computing framework",
         "role": "builder",  # role on a non-person must be dropped
         "raw_mentions": ["DStack"], "turn_ids": [2]},
    ]
    out = _clean_entities(rows, n_turns=10)
    person, tool = out[0], out[1]
    assert person["definition"] == "a security researcher on the team"
    assert person["role"] == "researcher"            # casefolded into the enum
    assert tool["definition"] == "a confidential-computing framework"
    assert tool["role"] is None                       # non-person → no role


def test_clean_entity_invalid_role_and_empty_definition_become_none():
    rows = [
        {"type": "person", "canonical_name": "X", "role": "wizard",
         "definition": "   ", "raw_mentions": ["X"], "turn_ids": []},
    ]
    out = _clean_entities(rows, n_turns=5)
    assert out[0]["role"] is None          # not in PERSON_ROLES
    assert out[0]["definition"] is None     # whitespace-only → None


def test_merge_keeps_longest_definition_and_first_role():
    rows = [
        {"type": "tool", "canonical_name": "DStack", "definition": "a framework",
         "role": None, "raw_mentions": ["DStack"], "turn_ids": [1]},
        {"type": "tool", "canonical_name": "dstack",
         "definition": "a confidential-computing framework for TEE deployment",
         "role": None, "raw_mentions": ["dstack"], "turn_ids": [2]},
    ]
    merged = merge_entities(rows)
    assert len(merged) == 1
    assert merged[0]["definition"] == "a confidential-computing framework for TEE deployment"
    assert sorted(merged[0]["raw_mentions"]) == ["DStack", "dstack"]
    assert merged[0]["turn_ids"] == [1, 2]


def test_merge_first_nonempty_role_wins():
    rows = [
        {"type": "person", "canonical_name": "Sam", "definition": None, "role": None,
         "raw_mentions": ["Sam"], "turn_ids": [1]},
        {"type": "person", "canonical_name": "Sam", "definition": None,
         "role": "builder", "raw_mentions": ["Sam"], "turn_ids": [2]},
    ]
    merged = merge_entities(rows)
    assert len(merged) == 1 and merged[0]["role"] == "builder"


def test_merge_is_backward_compatible_with_fieldless_rows():
    # Rows lacking definition/role (legacy / bake-off shape) must still merge.
    rows = [
        {"type": "topic", "canonical_name": "attestation",
         "raw_mentions": ["attestation"], "turn_ids": [1]},
        {"type": "topic", "canonical_name": "attestation",
         "raw_mentions": ["remote attestation"], "turn_ids": [2]},
    ]
    merged = merge_entities(rows)
    assert len(merged) == 1
    assert merged[0].get("definition") is None and merged[0].get("role") is None
    assert sorted(merged[0]["raw_mentions"]) == ["attestation", "remote attestation"]
