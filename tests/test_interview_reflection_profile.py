"""
S3 tests — profile extraction node (agent.profile_node).

LLM mocked. Verifies the pure-code guard (_build_profile) enforces the
collaboration-profile contract regardless of what the model returns:
  - tags normalized onto the closed taxonomy; off-vocab dropped
  - offers/needs/interests entries dropped unless quote-anchored
  - credibility kept on offers only, stage validated
  - LLM failure → empty profile, no crash

The node is called directly (it does not depend on the graph wiring, which the
themes/ownership nodes still own until S4).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from skills.interview_reflection.agent import profile_node


def _stub(payload: dict):
    class _S:
        def invoke(self, _messages):
            return SimpleNamespace(content=json.dumps(payload))
    return lambda *_a, **_k: _S()


def _state(transcript: str = "INTERVIEWER: hi\nINTERVIEWEE: I shipped a thing.") -> dict:
    return {
        "transcript": transcript,
        "interviewee_slug": "leo",
        "team_context": {},
        "deterministic": {},
    }


def test_profile_parses_and_normalizes(monkeypatch):
    payload = {
        "building": "Solana consumer payments app",
        "building_tags": ["payments", "ML", "totally-made-up"],  # ML→ai-ml, junk dropped
        "stage": "early-traction",
        "offers": [{
            "text": "two years of contract security audits",
            "tags": ["security", "smart-contract"],   # → security-privacy, smart-contracts
            "quote": "I spent two years doing contract security audits",
            "credibility": "demonstrated",
        }],
        "needs": [{
            "text": "token economics help",
            "tags": ["tokenomics"],
            "quote": "I'm stuck on our token economics",
        }],
    }
    monkeypatch.setattr("config.get_llm", _stub(payload))

    profile = profile_node(_state())["collaboration_profile"]

    assert profile["building"] == "Solana consumer payments app"
    assert profile["building_tags"] == ["payments", "ai-ml"]   # junk dropped, ML mapped
    assert profile["stage"] == "early-traction"
    assert profile["offers"][0]["tags"] == ["security-privacy", "smart-contracts"]
    assert profile["offers"][0]["credibility"] == "demonstrated"
    assert profile["needs"][0]["quote"] == "I'm stuck on our token economics"


def test_entry_without_quote_is_dropped(monkeypatch):
    payload = {
        "offers": [
            {"text": "has a quote", "tags": ["frontend"], "quote": "I built the frontend"},
            {"text": "no quote here", "tags": ["backend"]},          # dropped
            {"text": "empty quote", "tags": ["ops"], "quote": "  "},  # dropped
        ],
    }
    monkeypatch.setattr("config.get_llm", _stub(payload))

    profile = profile_node(_state())["collaboration_profile"]
    assert len(profile["offers"]) == 1
    assert profile["offers"][0]["text"] == "has a quote"


def test_invalid_stage_and_bad_credibility_nulled(monkeypatch):
    payload = {
        "stage": "scaling-to-the-moon",   # not a valid stage → None
        "needs": [{
            "text": "x", "tags": [], "quote": "q",
            "credibility": "demonstrated",   # credibility ignored on needs
        }],
    }
    monkeypatch.setattr("config.get_llm", _stub(payload))

    profile = profile_node(_state())["collaboration_profile"]
    assert profile["stage"] is None
    assert profile["needs"][0]["credibility"] is None


def test_llm_failure_returns_empty_profile(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("llm offline")
    monkeypatch.setattr("config.get_llm", _boom)

    profile = profile_node(_state())["collaboration_profile"]
    assert profile["building"] is None
    assert profile["offers"] == []
    assert profile["needs"] == []
    assert profile["stage"] is None


def test_malformed_json_returns_empty_profile(monkeypatch):
    class _S:
        def invoke(self, _m):
            return SimpleNamespace(content="not json at all")
    monkeypatch.setattr("config.get_llm", lambda *_a, **_k: _S())

    profile = profile_node(_state())["collaboration_profile"]
    assert profile["offers"] == [] and profile["building"] is None
