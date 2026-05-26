"""
Step 6 tests — guardrails: key whitelist, long-quote stripping, evidence-quote
gating, name redaction, leakage detection. Run over all Step 3 fixtures with a
calibrated LLM stub so the full skill pipeline (deterministic → agent →
guardrails) can be exercised end-to-end offline.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from skills.interview_reflection.config import (
    ALLOWED_INTERVIEWEE_OUTPUT_KEYS,
    ALLOWED_NOVEL_OUTPUT_KEYS,
    MIN_LEAKAGE_SUBSTRING_LENGTH,
)
from skills.interview_reflection.guardrails import InterviewReflectionFilter
from skills.interview_reflection.models import TranscriptInput
from skills.interview_reflection import run_skill


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "interview_reflection"


def _slugs() -> list[str]:
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.txt"))


def _benign_llm_stub():
    """LLM stub: returns short, fixture-agnostic JSON that won't trip the filter.

    Cycles profile → rubric items. Quotes are benign (not transcript spans) so
    the leakage scan finds nothing to redact.
    """
    calls = {"n": 0}

    def _factory(*_a, **_k):
        class _S:
            def invoke(self, _m):
                calls["n"] += 1
                if calls["n"] % 2 == 1:
                    payload = {
                        "building": "a consumer app",
                        "building_tags": ["consumer-social"],
                        "offers": [{"text": "frontend help", "tags": ["frontend"],
                                    "quote": "benign offer quote"}],
                    }
                else:
                    payload = {"items": {f"CO{i}": {"score": 4, "quote": "ev"} for i in range(1, 6)}}
                return SimpleNamespace(content=json.dumps(payload))
        return _S()
    return _factory


@pytest.mark.parametrize("slug", _slugs())
def test_no_long_transcript_substring_leaks(slug, monkeypatch):
    """For every fixture: no ≥60-char chunk of the raw transcript should appear in output."""
    transcript = (FIXTURE_DIR / f"{slug}.txt").read_text()
    monkeypatch.setattr("config.get_llm", _benign_llm_stub())

    response = run_skill(
        [TranscriptInput(transcript=transcript, interviewee_slug="leo")]
    )
    serialised = str(response.results)

    for i in range(0, len(transcript) - MIN_LEAKAGE_SUBSTRING_LENGTH + 1, 7):
        chunk = transcript[i : i + MIN_LEAKAGE_SUBSTRING_LENGTH]
        assert chunk not in serialised, (
            f"{slug}: transcript chunk leaked into output: {chunk[:60]!r}"
        )


def test_filter_drops_unknown_keys():
    f = InterviewReflectionFilter()
    out = f.apply(
        [{
            "submission_id": "s1",
            "interviewee_slug": "leo",
            "themes": ["a"],
            "attribution_patterns": {"internal": 1.0, "external": 0.0},
            "session_summary": "summary",
            "suggested_next_questions": ["q?"],
            "raw_transcript": "this should not leave",
            "internal_debug": {"secret": True},
        }],
        raw_transcripts=["unrelated"],
    )
    keys = set(out[0].keys())
    assert "raw_transcript" not in keys
    assert "internal_debug" not in keys
    assert keys <= ALLOWED_NOVEL_OUTPUT_KEYS | {"_leakage_warning"}


def test_long_quote_in_novel_output_is_redacted():
    # Long enough to exceed every per-field cap (themes=120, summary=400, etc.)
    long_string = "I shipped this thing and the partner did not show up " * 10  # ~530 chars
    f = InterviewReflectionFilter()
    out = f.apply(
        [{
            "submission_id": "s1",
            "interviewee_slug": "leo",
            "themes": [long_string],
            "attribution_patterns": {"internal": 0.5, "external": 0.5},
            "session_summary": long_string,
            "suggested_next_questions": ["short ok"],
        }],
        raw_transcripts=[long_string],
    )
    assert "[REDACTED LONG QUOTE]" in out[0]["themes"]
    assert out[0]["session_summary"] == "[REDACTED LONG QUOTE]"


def test_per_field_quote_caps_allow_normal_session_summary():
    """A 2-sentence session_summary must NOT be over-redacted as a long quote."""
    summary = (
        "The interviewee owns the shipping miss and proposes a 90-minute "
        "checkpoint as a countermeasure. Outbound is the gap to monthly milestone."
    )  # ~210 chars — over old 120 cap, under new 400 cap
    assert len(summary) > 120
    assert len(summary) < 400
    f = InterviewReflectionFilter()
    out = f.apply(
        [{
            "submission_id": "s1",
            "interviewee_slug": "leo",
            "themes": ["shipping miss"],
            "attribution_patterns": {"internal": 0.8, "external": 0.2},
            "session_summary": summary,
            "suggested_next_questions": ["What's the next test?"],
        }],
        raw_transcripts=["unrelated transcript content"],
    )
    assert out[0]["session_summary"] == summary


def test_modal_verbs_at_sentence_start_not_redacted():
    """'Can you elaborate' must not become '[REDACTED NAME] you elaborate'."""
    f = InterviewReflectionFilter(cohort_people={"leo"})
    out = f.apply(
        [{
            "submission_id": "s1",
            "interviewee_slug": "leo",
            "themes": ["shipping cadence"],
            "attribution_patterns": {"internal": 0.8, "external": 0.2},
            "session_summary": "Short.",
            "suggested_next_questions": [
                "Can you elaborate on the cohort channel?",
                "Could you describe the 90-minute checkpoint?",
                "Would Leo change anything about the outbound cadence?",
                "Should the launcher icon stay moved?",
                "Will the Tuesday block hold?",
            ],
        }],
        raw_transcripts=[],
    )
    for q in out[0]["suggested_next_questions"]:
        assert "[REDACTED NAME]" not in q, f"false positive in: {q}"


def test_evidence_quotes_dropped_when_share_false():
    f = InterviewReflectionFilter()
    out = f.apply(
        [{
            "submission_id": "s1",
            "interviewee_slug": "leo",
            "themes": [],
            "attribution_patterns": {"internal": 0.5, "external": 0.5},
            "session_summary": "",
            "suggested_next_questions": [],
            "share_with_interviewee": False,
            "interviewee_output": {
                "submission_id": "s1",
                "interviewee_slug": "leo",
                "themes": [],
                "ownership_prompts": [],
                "evidence_quotes": ["This is a quote we should NEVER see"],
            },
        }],
        raw_transcripts=[],
    )
    assert "interviewee_output" not in out[0]


def test_evidence_quotes_preserved_when_share_true():
    f = InterviewReflectionFilter()
    out = f.apply(
        [{
            "submission_id": "s1",
            "interviewee_slug": "leo",
            "themes": [],
            "attribution_patterns": {"internal": 0.5, "external": 0.5},
            "session_summary": "",
            "suggested_next_questions": [],
            "share_with_interviewee": True,
            "interviewee_output": {
                "submission_id": "s1",
                "interviewee_slug": "leo",
                "themes": ["t"],
                "ownership_prompts": ["p"],
                "evidence_quotes": ["short quote ok"],
            },
        }],
        raw_transcripts=[],
    )
    assert "interviewee_output" in out[0]
    assert out[0]["interviewee_output"]["evidence_quotes"] == ["short quote ok"]
    assert set(out[0]["interviewee_output"].keys()) <= ALLOWED_INTERVIEWEE_OUTPUT_KEYS


def test_unknown_names_are_redacted():
    """Mid-sentence unknown names get redacted; cohort names + protected tokens pass."""
    f = InterviewReflectionFilter(cohort_people={"leo", "mira"})
    out = f.apply(
        [{
            "submission_id": "s1",
            "interviewee_slug": "leo",
            "themes": ["the work was done by Leo on time", "the demo was blocked by Eddie"],
            "attribution_patterns": {"internal": 0.5, "external": 0.5},
            # Mid-sentence "Eddie" after "; " — should be redacted.
            # Mid-sentence "Leo" and "Mira" — cohort names, should pass.
            "session_summary": "the team paired well with Leo and Mira; Eddie did not show up.",
            "suggested_next_questions": [],
        }],
        raw_transcripts=[],
    )
    summary = out[0]["session_summary"]
    assert "Leo" in summary
    assert "Mira" in summary
    assert "Eddie" not in summary
    assert "[REDACTED NAME]" in summary

    themes_joined = " | ".join(out[0]["themes"])
    assert "Leo" in themes_joined
    assert "Eddie" not in themes_joined


def test_sentence_start_capitals_are_not_treated_as_names():
    """Capitalised English words at the start of a sentence must pass through.

    This is the bug that triggered the policy change — words like 'Outbound',
    'Shipping', 'Friday', 'Loom' kept getting redacted as if they were proper
    nouns just because they sat at the start of a clause."""
    f = InterviewReflectionFilter(cohort_people=set())
    out = f.apply(
        [{
            "submission_id": "s1",
            "interviewee_slug": "leo",
            "themes": ["shipping cadence"],
            "attribution_patterns": {"internal": 0.5, "external": 0.5},
            "session_summary": "Outbound is the gap. Shipping is on track. Friday will be a stretch.",
            "suggested_next_questions": [],
        }],
        raw_transcripts=[],
    )
    summary = out[0]["session_summary"]
    assert summary == "Outbound is the gap. Shipping is on track. Friday will be a stretch."
