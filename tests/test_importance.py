"""Phase 3.5b C14 — importance scoring tests (fake LLM)."""
from __future__ import annotations

import json

from transcripts.importance import BATCH, DEFAULT_IMPORTANCE, score_importance


class FakeLLM:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)
        payload = self.payloads.pop(0) if self.payloads else {"scores": []}

        class R:
            content = json.dumps(payload)
        R.content = json.dumps(payload)
        return R()


def _items(n, kind="action"):
    return [{"type": kind, "description": f"item {i}"} for i in range(n)]


def test_scores_returned_in_order():
    llm = FakeLLM([{"scores": [7, 3]}])
    assert score_importance(_items(2), llm=llm) == [7, 3]


def test_empty_items_no_call():
    llm = FakeLLM([])
    assert score_importance([], llm=llm) == []
    assert llm.calls == []


def test_batching_over_batch_size():
    llm = FakeLLM([{"scores": [5] * BATCH}, {"scores": [6, 6]}])
    out = score_importance(_items(BATCH + 2), llm=llm)
    assert len(llm.calls) == 2
    assert out == [5] * BATCH + [6, 6]


def test_clamping_and_junk_coercion():
    llm = FakeLLM([{"scores": [0, 99, "8", None, 3.7]}])
    out = score_importance(_items(5), llm=llm)
    assert out == [1, 10, 8, DEFAULT_IMPORTANCE, 3]


def test_short_response_padded():
    llm = FakeLLM([{"scores": [9]}])
    out = score_importance(_items(3), llm=llm)
    assert out == [9, DEFAULT_IMPORTANCE, DEFAULT_IMPORTANCE]


def test_failure_returns_default():
    class Broken:
        def invoke(self, messages):
            raise ConnectionError("down")
    out = score_importance(_items(4), llm=Broken())
    assert out == [DEFAULT_IMPORTANCE] * 4


def test_owner_in_prompt():
    llm = FakeLLM([{"scores": [5]}])
    score_importance(
        [{"type": "commitment", "description": "pay for X", "owner_raw_text": "LSDan"}],
        llm=llm,
    )
    assert "owner: LSDan" in llm.calls[0][1].content
