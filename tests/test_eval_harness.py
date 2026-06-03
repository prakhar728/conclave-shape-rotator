"""Phase 3.5.0 C3 — bake-off harness tests (fake LLM, no Ollama needed).

Covers: chunking turn-id integrity, both extraction strategies' parse +
merge behavior, fuzzy matching, F1 math, and report rendering shape.
"""
from __future__ import annotations

import json

import pytest

from transcripts.extract_bakeoff import (
    chunk_turns,
    render_chunk,
    extract_one_prompt,
    extract_per_type,
    merge_entities,
    dedupe_obligations,
    token_set_ratio,
)
from transcripts.eval_bakeoff import (
    PRF,
    entity_pair_score,
    greedy_match,
    obligation_pair_score,
    render_report,
    score_transcript,
    BakeoffScore,
)


# ---------------------------------------------------------------------------
# Fake LLM
# ---------------------------------------------------------------------------

class FakeLLM:
    """Returns canned JSON; records the system prompts it saw."""

    def __init__(self, payloads):
        # payloads: list of dicts returned in order, cycling on exhaustion
        self.payloads = payloads
        self.calls = []
        self.i = 0

    def invoke(self, messages):
        self.calls.append(messages)
        payload = self.payloads[min(self.i, len(self.payloads) - 1)]
        self.i += 1

        class R:
            content = json.dumps(payload)
        return R()


SEGS = [
    {"speaker": "Ada", "text": "I will ship the importer by Friday."},
    {"speaker": "Bob", "text": "We decided to use SQLite for storage."},
    {"speaker": "Ada", "text": "What about the reranker question?"},
]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def test_chunk_turns_preserves_turn_ids():
    chunks = chunk_turns(SEGS, max_tokens=10_000)
    assert len(chunks) == 1
    assert [tid for tid, _ in chunks[0]] == [0, 1, 2]


def test_chunk_turns_overlap():
    # Force tiny chunks: each segment ~15 tokens at len/4 + 6
    chunks = chunk_turns(SEGS, max_tokens=20, overlap_turns=1)
    assert len(chunks) >= 2
    # Overlap: first turn of chunk N+1 == last turn of chunk N
    for a, b in zip(chunks, chunks[1:]):
        assert b[0][0] == a[-1][0]


def test_render_chunk_format():
    chunks = chunk_turns(SEGS, max_tokens=10_000)
    text = render_chunk(chunks[0])
    assert "[0] Ada: I will ship the importer by Friday." in text
    assert "[2] Ada: What about the reranker question?" in text


# ---------------------------------------------------------------------------
# Extraction strategies (fake LLM)
# ---------------------------------------------------------------------------

ONE_PROMPT_PAYLOAD = {
    "entities": [
        {"type": "person", "canonical_name": "Ada Lovelace",
         "raw_mentions": ["Ada"], "turn_ids": [0, 2]},
        {"type": "tool", "canonical_name": "SQLite",
         "raw_mentions": ["SQLite"], "turn_ids": [1]},
    ],
    "obligations": [
        {"type": "action", "description": "Ada will ship the importer by Friday",
         "source_quote": "I will ship the importer by Friday",
         "turn_ids": [0], "owner_raw_text": "Ada",
         "due_date_raw": "Friday", "status_inferred": "open"},
        {"type": "decision", "description": "Use SQLite for storage",
         "source_quote": "We decided to use SQLite",
         "turn_ids": [1], "owner_raw_text": None,
         "due_date_raw": None, "status_inferred": "resolved"},
    ],
}


def test_extract_one_prompt_single_call_per_chunk():
    llm = FakeLLM([ONE_PROMPT_PAYLOAD])
    result = extract_one_prompt(SEGS, llm=llm)
    assert len(llm.calls) == 1  # one chunk → one call
    assert {e["canonical_name"] for e in result["entities"]} == {"Ada Lovelace", "SQLite"}
    assert {o["type"] for o in result["obligations"]} == {"action", "decision"}


def test_extract_per_type_six_calls_per_chunk():
    entities_payload = {"entities": ONE_PROMPT_PAYLOAD["entities"]}
    action_payload = {"obligations": [ONE_PROMPT_PAYLOAD["obligations"][0]]}
    empty = {"obligations": []}
    # order: entities, action, decision, commitment, open_question, blocker
    decision_payload = {"obligations": [ONE_PROMPT_PAYLOAD["obligations"][1]]}
    llm = FakeLLM([entities_payload, action_payload, decision_payload,
                   empty, empty, empty])
    result = extract_per_type(SEGS, llm=llm)
    assert len(llm.calls) == 6  # 1 entities + 5 types, single chunk
    assert {o["type"] for o in result["obligations"]} == {"action", "decision"}


def test_extract_per_type_drops_smuggled_types():
    """A per-type 'action' prompt returning a decision row must be discarded."""
    entities_payload = {"entities": []}
    smuggled = {"obligations": [
        {"type": "decision", "description": "smuggled decision",
         "source_quote": "x", "turn_ids": [0], "owner_raw_text": None,
         "due_date_raw": None, "status_inferred": "open"},
    ]}
    empty = {"obligations": []}
    llm = FakeLLM([entities_payload, smuggled, empty, empty, empty, empty])
    result = extract_per_type(SEGS, llm=llm)
    assert result["obligations"] == []  # smuggled row dropped from the action call


def test_invalid_rows_dropped():
    bad = {
        "entities": [
            {"type": "alien", "canonical_name": "??", "raw_mentions": [], "turn_ids": []},
            {"type": "person", "canonical_name": "", "raw_mentions": [], "turn_ids": []},
        ],
        "obligations": [
            {"type": "wish", "description": "x", "source_quote": "", "turn_ids": [0],
             "owner_raw_text": None, "due_date_raw": None, "status_inferred": "open"},
            {"type": "action", "description": "valid one", "source_quote": "",
             "turn_ids": [99], "owner_raw_text": None, "due_date_raw": None,
             "status_inferred": "bogus"},
        ],
    }
    llm = FakeLLM([bad])
    result = extract_one_prompt(SEGS, llm=llm)
    assert result["entities"] == []
    assert len(result["obligations"]) == 1
    ob = result["obligations"][0]
    assert ob["turn_ids"] == []           # 99 out of range for 3 segments
    assert ob["status_inferred"] == "unclear"  # bogus → coerced


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

def test_merge_entities_unions():
    rows = [
        {"type": "person", "canonical_name": "Ada", "raw_mentions": ["Ada"], "turn_ids": [0]},
        {"type": "person", "canonical_name": "ada", "raw_mentions": ["Ms. Ada"], "turn_ids": [2]},
    ]
    merged = merge_entities(rows)
    assert len(merged) == 1
    assert merged[0]["turn_ids"] == [0, 2]
    assert "Ms. Ada" in merged[0]["raw_mentions"]


def test_dedupe_obligations_merges_chunk_echoes():
    rows = [
        {"type": "action", "description": "Ada will ship the importer by Friday",
         "source_quote": "", "turn_ids": [0], "owner_raw_text": "Ada",
         "due_date_raw": None, "status_inferred": "open"},
        {"type": "action", "description": "Ada will ship the importer Friday",
         "source_quote": "", "turn_ids": [1], "owner_raw_text": "Ada",
         "due_date_raw": None, "status_inferred": "open"},
        {"type": "decision", "description": "Ada will ship the importer by Friday",
         "source_quote": "", "turn_ids": [0], "owner_raw_text": None,
         "due_date_raw": None, "status_inferred": "open"},
    ]
    out = dedupe_obligations(rows)
    # same-type near-dups merge; different type survives
    assert len(out) == 2
    assert out[0]["turn_ids"] == [0, 1]


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

def test_token_set_ratio_basics():
    assert token_set_ratio("ship the importer", "ship the importer") == 1.0
    assert token_set_ratio("a b c", "d e f") == 0.0
    assert 0 < token_set_ratio("ship importer Friday", "importer ships Monday") < 1


def test_greedy_match_one_to_one():
    preds = [{"description": "ship importer Friday", "turn_ids": [0]},
             {"description": "ship importer Friday", "turn_ids": [0]}]
    golds = [{"description": "ship the importer by Friday", "turn_ids": [0]}]
    m = greedy_match(preds, golds, obligation_pair_score, 0.3)
    assert len(m) == 1  # second pred can't double-claim the gold


def test_entity_pair_score_containment():
    pred = {"canonical_name": "Andrew", "raw_mentions": ["Andrew"]}
    gold = {"canonical_name": "Andrew Miller", "raw_mentions": ["Andrew Miller"]}
    assert entity_pair_score(pred, gold) >= 0.9


def test_score_transcript_prf_math():
    pred = {
        "entities": [
            {"type": "person", "canonical_name": "Ada Lovelace", "raw_mentions": ["Ada"], "turn_ids": [0]},
            {"type": "tool", "canonical_name": "Hallucinated", "raw_mentions": ["Hallucinated"], "turn_ids": []},
        ],
        "obligations": [
            {"type": "action", "description": "Ada will ship the importer by Friday",
             "source_quote": "", "turn_ids": [0], "owner_raw_text": "Ada",
             "due_date_raw": "Friday", "status_inferred": "open"},
        ],
    }
    gold = {
        "entities": [
            {"type": "person", "canonical_name": "Ada Lovelace", "raw_mentions": ["Ada"], "turn_ids": [0]},
        ],
        "obligations": [
            {"type": "action", "description": "Ada ships the importer by Friday",
             "source_quote": "", "turn_ids": [0], "owner_raw_text": "Ada",
             "due_date_raw": "Friday", "status_inferred": "open"},
            {"type": "decision", "description": "Use SQLite", "source_quote": "",
             "turn_ids": [1], "owner_raw_text": None, "due_date_raw": None,
             "status_inferred": "resolved"},
        ],
    }
    s = score_transcript(pred, gold)
    assert s.obligations_by_type["action"].tp == 1
    assert s.obligations_by_type["decision"].fn == 1
    assert s.entities_overall.tp == 1
    assert s.entities_overall.fp == 1
    # macro-F1 averages only types with gold support (action=1.0, decision=0.0)
    assert s.obligation_macro_f1 == pytest.approx(0.5)


def test_prf_zero_division_guards():
    p = PRF()
    assert p.precision == 0.0 and p.recall == 0.0 and p.f1 == 0.0


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def test_render_report_shape():
    s1 = BakeoffScore()
    s1.obligations_by_type["action"] = PRF(tp=2, fp=1, fn=0)
    s1.entities_overall = PRF(tp=5, fp=2, fn=3)
    s2 = BakeoffScore()
    s2.obligations_by_type["action"] = PRF(tp=1, fp=0, fn=1)
    s2.entities_overall = PRF(tp=4, fp=1, fn=4)
    report = render_report(
        {"slug-a": {"one_prompt": s1, "per_type": s2}},
        model_id="fake-model",
    )
    assert "# Q1 bake-off results" in report
    assert "fake-model" in report
    assert "## Aggregate" in report
    assert "## slug-a" in report
    assert "obligation macro-F1" in report
    assert "entity F1" in report
    assert "one_prompt" in report and "per_type" in report
