"""Phase 3.5b C13 — production extraction tests (fake LLM)."""
from __future__ import annotations

import json

import pytest

from transcripts.extract import (
    EXTRACT_PROMPT_VERSION,
    ExtractionResult,
    dedupe_obligations,
    extract_from_chunk,
    merge_entities,
)


class FakeLLM:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)

        class R:
            content = json.dumps(self.payload)
        R.content = json.dumps(self.payload)
        return R()


GOOD = {
    "entities": [
        {"type": "person", "canonical_name": "Ada Lovelace",
         "raw_mentions": ["Ada"], "turn_ids": [0, 3]},
    ],
    "obligations": [
        {"type": "action",
         "description": "Ada will ship the importer, tests first, by Friday",
         "source_quote": "I'll ship the importer by Friday",
         "turn_ids": [0, 2, 3], "owner_raw_text": "Ada",
         "due_date_raw": "Friday", "status_inferred": "open"},
    ],
}


def test_extract_happy_path():
    llm = FakeLLM(GOOD)
    r = extract_from_chunk("[0] Ada: I'll ship...", turn_count=4, llm=llm)
    assert isinstance(r, ExtractionResult)
    assert r.entities[0]["canonical_name"] == "Ada Lovelace"
    assert r.obligations[0]["turn_ids"] == [0, 2, 3]


def test_context_header_prepended():
    llm = FakeLLM(GOOD)
    extract_from_chunk("[0] Ada: hi", context_header="Sprint sync, May 30", llm=llm)
    human = llm.calls[0][1].content
    assert human.index("Context: Sprint sync") < human.index("[0] Ada: hi")
    assert "<chunk>" in human


def test_consolidation_rule_in_prompt():
    llm = FakeLLM(GOOD)
    extract_from_chunk("[0] Ada: hi", llm=llm)
    system = llm.calls[0][0].content
    assert "CONSOLIDATION" in system
    assert "ENTITY DISCIPLINE" in system


def test_turn_bound_enforced():
    payload = {
        "entities": [],
        "obligations": [{
            "type": "action", "description": "x", "source_quote": "",
            "turn_ids": [0, 7, 99], "owner_raw_text": None,
            "due_date_raw": None, "status_inferred": "open",
        }],
    }
    r = extract_from_chunk("[0] A: x", turn_count=8, llm=FakeLLM(payload))
    assert r.obligations[0]["turn_ids"] == [0, 7]


def test_bad_rows_dropped_and_coerced():
    payload = {
        "entities": [
            {"type": "starship", "canonical_name": "X", "raw_mentions": [], "turn_ids": []},
            {"type": "tool", "canonical_name": "  ", "raw_mentions": [], "turn_ids": []},
        ],
        "obligations": [
            {"type": "action", "description": "ok", "source_quote": "",
             "turn_ids": [], "owner_raw_text": "", "due_date_raw": None,
             "status_inferred": "maybe"},
        ],
    }
    r = extract_from_chunk("[0] A: x", llm=FakeLLM(payload))
    assert r.entities == []
    assert r.obligations[0]["status_inferred"] == "unclear"
    assert r.obligations[0]["owner_raw_text"] is None  # "" → null discipline


def test_output_error_returns_empty():
    class GarbageLLM:
        def invoke(self, messages):
            class R:
                content = "I cannot help with that."
            return R()
    r = extract_from_chunk("[0] A: x", llm=GarbageLLM())
    assert r.entities == [] and r.obligations == []


def test_merge_and_dedupe_reexported():
    merged = merge_entities([
        {"type": "person", "canonical_name": "Ada", "raw_mentions": ["Ada"], "turn_ids": [1]},
        {"type": "person", "canonical_name": "ada", "raw_mentions": ["Ms Ada"], "turn_ids": [2]},
    ])
    assert len(merged) == 1 and merged[0]["turn_ids"] == [1, 2]
    deduped = dedupe_obligations([
        {"type": "action", "description": "ship the importer by Friday", "turn_ids": [1]},
        {"type": "action", "description": "ship importer by Friday", "turn_ids": [2]},
    ])
    assert len(deduped) == 1 and deduped[0]["turn_ids"] == [1, 2]


def test_prompt_version_exists():
    assert EXTRACT_PROMPT_VERSION  # backfill staleness key
