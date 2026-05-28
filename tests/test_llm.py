"""C6 gate — `transcripts/llm.py` (reliable JSON invoke + access guard).

Asserts the contract documented in IMPLEMENTATION_PLAN.md §G4 / §H C6:

- Valid JSON parses on the first try.
- Garbage on first try + valid on the repair re-prompt → returns the
  parsed dict (the bracket-match-then-repair pipeline).
- ``required_keys`` missing → ``LLMOutputError``.
- 402 / connection / DNS / 503 errors at invoke time → ``LLMUnavailable``.
- A real backend never gets touched in the unit suite — FakeLLM only.

One opt-in ``@pytest.mark.requires_ollama`` test exercises the same
``invoke_json`` against the local ``qwen2.5-conclave`` model. Auto-skipped
when Ollama isn't running or the model isn't pulled, so the green-trunk
rule still holds.
"""
from __future__ import annotations

import json

import pytest
from langchain_core.messages import HumanMessage, SystemMessage

from transcripts.llm import (
    LLMOutputError,
    LLMUnavailable,
    _extract_json,
    _is_unavailable,
    invoke_json,
)


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeLLM:
    """Returns the next canned response per .invoke() call.

    Accept either str (wrapped) or BaseException (raised). Records the
    messages list for each call so tests can assert on the repair prompt.
    """

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        if not self._responses:
            raise AssertionError("FakeLLM ran out of canned responses")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return type("Resp", (), {"content": item})()


def _msgs(user: str = "do the thing") -> list:
    return [SystemMessage(content="sys"), HumanMessage(content=user)]


# ---------------------------------------------------------------------------
# _extract_json — bracket matcher
# ---------------------------------------------------------------------------

def test_extract_json_finds_balanced_object_inside_prose():
    payload = 'reasoning: here it is\n```\n{"a": 1, "b": [1,2]}\n```\nthe end'
    assert _extract_json(payload) == {"a": 1, "b": [1, 2]}


def test_extract_json_handles_nested_objects_and_quoted_braces():
    payload = '{"outer": {"inner": "}{"}, "n": 2}'
    assert _extract_json(payload) == {"outer": {"inner": "}{"}, "n": 2}


def test_extract_json_returns_none_on_no_object():
    assert _extract_json("") is None
    assert _extract_json("no braces here") is None


def test_extract_json_returns_none_on_unparseable_balanced_block():
    # Balanced braces but invalid JSON inside.
    assert _extract_json("{not, valid: json}") is None


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_invoke_json_parses_first_attempt_without_retry():
    fake = FakeLLM('{"summary": "ok", "n": 3}')
    out = invoke_json(_msgs(), llm=fake, required_keys=("summary", "n"))
    assert out == {"summary": "ok", "n": 3}
    assert len(fake.calls) == 1   # no repair needed


def test_invoke_json_tolerates_reasoning_prefix_and_code_fences():
    fake = FakeLLM('Sure! Here is the JSON:\n```json\n{"k": "v"}\n```\n')
    assert invoke_json(_msgs(), llm=fake) == {"k": "v"}


# ---------------------------------------------------------------------------
# Repair retry
# ---------------------------------------------------------------------------

def test_invoke_json_repairs_then_succeeds():
    fake = FakeLLM("definitely not json", '{"summary": "fixed"}')
    out = invoke_json(_msgs(), llm=fake, required_keys=("summary",))
    assert out == {"summary": "fixed"}
    assert len(fake.calls) == 2
    # The repair prompt echoes the model's bad output back so it can self-correct.
    repair_call = fake.calls[1]
    assert any("definitely not json" in getattr(m, "content", "") for m in repair_call)
    # And explicitly asks for raw JSON.
    assert any("ONE valid JSON" in getattr(m, "content", "") for m in repair_call)


def test_invoke_json_repair_failure_raises_output_error():
    fake = FakeLLM("garbage", "still garbage")
    with pytest.raises(LLMOutputError) as exc:
        invoke_json(_msgs(), llm=fake)
    assert "could not extract JSON" in str(exc.value)


def test_invoke_json_with_max_retries_0_skips_repair():
    fake = FakeLLM("garbage")
    with pytest.raises(LLMOutputError):
        invoke_json(_msgs(), llm=fake, max_retries=0)
    assert len(fake.calls) == 1


# ---------------------------------------------------------------------------
# Schema check
# ---------------------------------------------------------------------------

def test_invoke_json_missing_required_key_triggers_repair_then_raises():
    # First call: valid JSON but missing required key. Repair: same problem.
    fake = FakeLLM('{"other": 1}', '{"other": 2}')
    with pytest.raises(LLMOutputError) as exc:
        invoke_json(_msgs(), llm=fake, required_keys=("summary",))
    assert "summary" in str(exc.value)
    assert len(fake.calls) == 2  # one repair attempted


def test_invoke_json_missing_required_key_recoverable_by_repair():
    fake = FakeLLM('{"other": 1}', '{"summary": "now present"}')
    out = invoke_json(_msgs(), llm=fake, required_keys=("summary",))
    assert out == {"summary": "now present"}


# ---------------------------------------------------------------------------
# LLMUnavailable mapping
# ---------------------------------------------------------------------------

class _Boom(Exception):
    """Generic provider-side error placeholder for the unavailable map."""


def test_unavailable_classifier_catches_known_strings():
    assert _is_unavailable(_Boom("Connection refused"))
    assert _is_unavailable(_Boom("Read timed out"))
    assert _is_unavailable(_Boom("HTTP 402 — out of credits"))
    assert _is_unavailable(_Boom("rate limit reached"))
    assert _is_unavailable(ConnectionError("daemon down"))
    # Non-network errors don't get swept up.
    assert not _is_unavailable(_Boom("bad prompt"))
    assert not _is_unavailable(ValueError("nope"))


def test_invoke_json_maps_connection_error_to_unavailable():
    fake = FakeLLM(ConnectionError("ollama daemon refused connection"))
    with pytest.raises(LLMUnavailable):
        invoke_json(_msgs(), llm=fake)


def test_invoke_json_maps_402_to_unavailable():
    fake = FakeLLM(_Boom("HTTP 402: credits exhausted"))
    with pytest.raises(LLMUnavailable):
        invoke_json(_msgs(), llm=fake)


def test_invoke_json_lets_non_provider_errors_bubble():
    """A bug in our own code should NOT be silently swallowed as LLMUnavailable."""
    class MyBug(Exception):
        pass
    fake = FakeLLM(MyBug("oops"))
    with pytest.raises(MyBug):
        invoke_json(_msgs(), llm=fake)


# ---------------------------------------------------------------------------
# Optional: live Ollama smoke (auto-skipped when daemon/model absent)
# ---------------------------------------------------------------------------

@pytest.mark.requires_ollama
def test_invoke_json_against_local_qwen():
    """End-to-end through `config.get_llm` against the actual local model.

    Asserts:
      - The full wiring (config → ChatOpenAI → Ollama → bracket parse) works.
      - qwen2.5-conclave honors a strict JSON instruction one-shot.
      - The schema check finds the required key.

    Skipped automatically when Ollama isn't running or the configured
    `CONCLAVE_OLLAMA_MODEL` isn't pulled — see tests/conftest.py.
    """
    import os
    os.environ["CONCLAVE_LLM_BACKEND"] = "ollama"
    # Re-read settings so the just-set env is picked up.
    import importlib
    import config
    importlib.reload(config)

    messages = [
        SystemMessage(content=(
            "You are a JSON-only API. Reply with ONE raw JSON object, no prose, "
            "no markdown fences, matching this exact schema:\n"
            '{"city": "<string>", "population_millions": <number>}'
        )),
        HumanMessage(content="What is the capital of France?"),
    ]
    out = invoke_json(messages, required_keys=("city",))
    assert isinstance(out, dict)
    assert "city" in out
    assert isinstance(out["city"], str) and out["city"].strip()
    # Be lenient on the value — model might say "Paris" or "paris" — but
    # if it produced JSON at all, our wiring works.
