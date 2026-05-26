"""
Step 5 tests — Layer 2 (agent) against the full Step 3 fixture set.

LLM is mocked. Each fixture gets a two-call stub calibrated to its
`.expected.yaml` (themes, attribution direction). The tests verify:

  1. Graph wires correctly: themes flow into ownership; both populate state.
  2. Output shape matches the I/O contract (Step 2 models).
  3. Mocked themes are passed through unchanged (no silent dropping).
  4. Ownership prompts present when human_attribution_bucket is external-leaning.
  5. Insufficient-signal fixtures: agent returns empty lists, neutral attribution.

LLM quality is NOT tested here — Step 10 (real transcripts) is the gate for that.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import yaml

from skills.interview_reflection.agent import run_agent
from skills.interview_reflection.deterministic import run_deterministic


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "interview_reflection"


def _slugs() -> list[str]:
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.txt"))


def _canned_for(expected: dict) -> tuple[dict, dict]:
    """Build (themes_response, ownership_response) calibrated to a fixture's expected.yaml."""
    themes = expected.get("expected_themes") or []
    bucket = expected.get("human_attribution_bucket") or expected.get("attribution_bucket")

    if bucket == "insufficient_signal":
        attribution = {"internal": 0.5, "external": 0.5}
        ownership_prompts: list[str] = []
        next_questions: list[str] = []
    elif bucket == "mostly_internal":
        attribution = {"internal": 0.8, "external": 0.2}
        ownership_prompts = []
        next_questions = [f"What's the next test on {t}?" for t in themes[:2]]
    elif bucket == "mostly_external":
        attribution = {"internal": 0.25, "external": 0.75}
        ownership_prompts = [
            f"When you say external cause on {t}, what part is yours?"
            for t in themes[:2]
        ]
        next_questions = [f"What would change next week if you owned {t}?" for t in themes[:2]]
    elif bucket == "shifting":
        attribution = {"internal": 0.55, "external": 0.45}
        ownership_prompts = [f"What made the shift on {t} stick?" for t in themes[:1]]
        next_questions = [f"Has the reframe on {t} held in the week since?" for t in themes[:1]]
    else:  # mixed or unknown
        attribution = {"internal": 0.5, "external": 0.5}
        ownership_prompts = [f"Which part of {t} is the lever you control?" for t in themes[:1]]
        next_questions = [f"How will you check progress on {t}?" for t in themes[:1]]

    themes_response = {
        "themes": themes,
        "session_summary": expected.get("notes", "").strip().splitlines()[0] if expected.get("notes") else "",
    }
    ownership_response = {
        "attribution_patterns": attribution,
        "ownership_prompts": ownership_prompts,
        "suggested_next_questions": next_questions,
    }
    return themes_response, ownership_response


def _make_llm_stub(responses: list[dict]):
    """Return a callable that mimics `get_llm()` — each invoke pops the next canned response."""
    queue = list(responses)

    class _Stub:
        def invoke(self, _messages):
            payload = queue.pop(0) if queue else {}
            return SimpleNamespace(content=json.dumps(payload))

    def _factory(*_args, **_kwargs):
        return _Stub()

    return _factory


@pytest.mark.parametrize("slug", _slugs())
def test_agent_on_fixture(slug, monkeypatch):
    transcript = (FIXTURE_DIR / f"{slug}.txt").read_text()
    expected = yaml.safe_load((FIXTURE_DIR / f"{slug}.expected.yaml").read_text())

    themes_resp, ownership_resp = _canned_for(expected)
    monkeypatch.setattr(
        "config.get_llm",
        _make_llm_stub([themes_resp, ownership_resp]),
    )

    det = run_deterministic(transcript)
    out = run_agent(
        transcript=transcript,
        interviewee_slug=expected.get("interviewee_slug", "unknown"),
        team_context={"success_dimensions": expected.get("team_context", "")},
        deterministic=det,
    )

    # Shape contract
    assert set(out.keys()) >= {
        "themes",
        "session_summary",
        "attribution_patterns",
        "ownership_prompts",
        "suggested_next_questions",
    }
    assert isinstance(out["themes"], list)
    assert isinstance(out["attribution_patterns"], dict)

    # Themes pass through unchanged from canned response
    assert out["themes"] == themes_resp["themes"]

    # Attribution shape
    assert "internal" in out["attribution_patterns"]
    assert "external" in out["attribution_patterns"]
    assert 0.0 <= out["attribution_patterns"]["internal"] <= 1.0
    assert 0.0 <= out["attribution_patterns"]["external"] <= 1.0

    # Bucket-specific behavior
    bucket = expected.get("human_attribution_bucket") or expected.get("attribution_bucket")
    if bucket == "insufficient_signal":
        assert out["ownership_prompts"] == []
        assert out["suggested_next_questions"] == []
        assert out["attribution_patterns"] == {"internal": 0.5, "external": 0.5}
    elif bucket == "mostly_external":
        assert len(out["ownership_prompts"]) >= 1, (
            f"{slug}: external-leaning bucket should produce ownership prompts"
        )


def test_agent_falls_back_when_llm_unavailable(monkeypatch):
    """If the LLM raises, the agent returns empty fields rather than crashing."""
    def _boom(*_a, **_k):
        raise RuntimeError("llm offline")

    monkeypatch.setattr("config.get_llm", _boom)

    det = run_deterministic("INTERVIEWER: Hi.\nINTERVIEWEE: I shipped a thing.")
    out = run_agent(
        transcript="INTERVIEWER: Hi.\nINTERVIEWEE: I shipped a thing.",
        interviewee_slug="x",
        team_context={},
        deterministic=det,
    )
    assert out["themes"] == []
    assert out["ownership_prompts"] == []
    assert out["suggested_next_questions"] == []
    # attribution falls back to Layer 1 ratio rather than crashing
    assert "internal" in out["attribution_patterns"]
    assert "external" in out["attribution_patterns"]


def test_agent_handles_malformed_llm_output(monkeypatch):
    """Non-JSON LLM output → empty themes/prompts, no exception."""
    def _bad_llm(*_a, **_k):
        class _S:
            def invoke(self, _m):
                return SimpleNamespace(content="this is not json at all")
        return _S()

    monkeypatch.setattr("config.get_llm", _bad_llm)

    det = run_deterministic("INTERVIEWER: Hi.\nINTERVIEWEE: I shipped a thing.")
    out = run_agent(
        transcript="INTERVIEWER: Hi.\nINTERVIEWEE: I shipped a thing.",
        interviewee_slug="x",
        team_context={},
        deterministic=det,
    )
    assert out["themes"] == []
    assert out["session_summary"] == ""
