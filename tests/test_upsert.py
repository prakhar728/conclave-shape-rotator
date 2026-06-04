"""Phase 3.5b C16 — Mem0-style upsert decision tests (fake LLM)."""
from __future__ import annotations

import json

from transcripts.upsert import UpsertDecision, decide_upsert


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


NEW = {"type": "action", "description": "Ada ships importer Friday",
       "owner_raw_text": "Ada", "status_inferred": "open"}
EXISTING = [
    {"id": "o1", "type": "action", "description": "Ada will ship the importer",
     "status_inferred": "open", "ingested_at": "2026-06-01"},
    {"id": "o2", "type": "action", "description": "Bob writes announcement",
     "status_inferred": "open", "ingested_at": "2026-06-01"},
]


def test_no_candidates_is_add_without_llm():
    llm = FakeLLM({"action": "NOOP", "target_id": "o1"})
    d = decide_upsert(NEW, [], llm=llm)
    assert d.action == "ADD" and llm.calls == []


def test_each_action_round_trips():
    for action in ("UPDATE", "DELETE", "NOOP"):
        d = decide_upsert(
            NEW, EXISTING,
            llm=FakeLLM({"action": action, "target_id": "o1", "reason": "r"}),
        )
        assert d.action == action and d.target_id == "o1"
    d = decide_upsert(NEW, EXISTING, llm=FakeLLM({"action": "ADD"}))
    assert d.action == "ADD" and d.target_id is None


def test_add_clears_spurious_target():
    d = decide_upsert(NEW, EXISTING, llm=FakeLLM({"action": "ADD", "target_id": "o1"}))
    assert d.action == "ADD" and d.target_id is None


def test_hallucinated_target_fails_safe_to_add():
    d = decide_upsert(
        NEW, EXISTING,
        llm=FakeLLM({"action": "DELETE", "target_id": "o999"}),
    )
    assert d.action == "ADD"
    assert "invalid target" in d.reason


def test_missing_target_on_update_fails_safe():
    d = decide_upsert(NEW, EXISTING, llm=FakeLLM({"action": "UPDATE"}))
    assert d.action == "ADD"


def test_invalid_action_fails_safe():
    d = decide_upsert(NEW, EXISTING, llm=FakeLLM({"action": "MERGE", "target_id": "o1"}))
    assert d.action == "ADD"


def test_case_insensitive_action():
    d = decide_upsert(NEW, EXISTING, llm=FakeLLM({"action": "noop", "target_id": "o2"}))
    assert d.action == "NOOP" and d.target_id == "o2"


def test_llm_failure_defaults_add():
    class Broken:
        def invoke(self, messages):
            raise ConnectionError("down")
    d = decide_upsert(NEW, EXISTING, llm=Broken())
    assert d.action == "ADD" and "llm failure" in d.reason


def test_prompt_contains_both_sides():
    llm = FakeLLM({"action": "NOOP", "target_id": "o1"})
    decide_upsert(NEW, EXISTING, llm=llm)
    human = llm.calls[0][1].content
    assert "<new>" in human and "<existing>" in human
    assert "Ada ships importer Friday" in human
    assert "id=o1" in human and "id=o2" in human
