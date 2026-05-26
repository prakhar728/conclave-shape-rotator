"""
S4 tests — Layer 2 agent graph (profile_node → rubric_node).

LLM is mocked with a two-call stub: first call returns a collaboration profile,
second returns the rubric items. Verifies graph wiring, output shape, and that
the rubric panel aggregates per the registry rules. LLM quality is not tested.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from skills.interview_reflection.agent import run_agent


def _two_call_stub(profile_payload: dict, items_payload: dict):
    """Factory mimicking get_llm(): 1st invoke → profile, 2nd → rubric items."""
    state = {"n": 0}

    class _Stub:
        def invoke(self, _messages):
            state["n"] += 1
            payload = profile_payload if state["n"] == 1 else items_payload
            return SimpleNamespace(content=json.dumps(payload))

    return lambda *_a, **_k: _Stub()


PROFILE = {
    "building": "Solana consumer payments app",
    "building_tags": ["payments"],
    "stage": "early-traction",
    "offers": [{"text": "frontend onboarding", "tags": ["frontend"],
                "quote": "I built the onboarding flow", "credibility": "demonstrated"}],
    "needs": [{"text": "sales outreach", "tags": ["sales"],
               "quote": "I am stuck on outbound"}],
}

# Full coachability (5/5), full agency (3/3); others empty → unreported.
ITEMS = {"items": {
    **{f"CO{i}": {"score": 4, "quote": "ev"} for i in range(1, 6)},
    **{f"LC{i}": {"score": 5, "quote": "ev"} for i in range(1, 4)},
}}


def test_graph_returns_profile_and_panel(monkeypatch):
    monkeypatch.setattr("config.get_llm", _two_call_stub(PROFILE, ITEMS))

    out = run_agent(
        transcript="INTERVIEWER: hi\nINTERVIEWEE: I built the onboarding flow.",
        interviewee_slug="leo",
        team_context={},
        deterministic={},
    )

    assert set(out.keys()) == {
        "collaboration_profile", "rubric_panel", "rationale", "summary", "bullets"
    }

    profile = out["collaboration_profile"]
    assert profile["building"] == "Solana consumer payments app"
    assert profile["building_tags"] == ["payments"]
    assert profile["offers"][0]["tags"] == ["frontend"]
    assert profile["needs"][0]["tags"] == ["sales-bd"]   # alias normalized

    panel = out["rubric_panel"]
    assert set(panel.keys()) == {
        "coachability", "agency", "proactivity", "goal_commitment", "progress"
    }
    assert panel["coachability"]["reported"] is True
    assert panel["coachability"]["score"] == 4.0
    assert panel["agency"]["reported"] is True
    # Rubrics with no scored items are unreported, not invented.
    assert panel["proactivity"]["reported"] is False
    assert panel["proactivity"]["score"] is None


def test_agent_falls_back_when_llm_unavailable(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("llm offline")
    monkeypatch.setattr("config.get_llm", _boom)

    out = run_agent(
        transcript="INTERVIEWER: Hi.\nINTERVIEWEE: I shipped a thing.",
        interviewee_slug="x",
        team_context={},
        deterministic={},
    )
    assert out["collaboration_profile"]["offers"] == []
    assert out["collaboration_profile"]["building"] is None
    for rubric in out["rubric_panel"].values():
        assert rubric["reported"] is False


def test_agent_handles_malformed_llm_output(monkeypatch):
    class _S:
        def invoke(self, _m):
            return SimpleNamespace(content="this is not json at all")
    monkeypatch.setattr("config.get_llm", lambda *_a, **_k: _S())

    out = run_agent(
        transcript="INTERVIEWER: Hi.\nINTERVIEWEE: I shipped a thing.",
        interviewee_slug="x",
        team_context={},
        deterministic={},
    )
    assert out["collaboration_profile"]["offers"] == []
    assert out["rubric_panel"]["coachability"]["reported"] is False
