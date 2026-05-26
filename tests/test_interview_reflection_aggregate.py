"""
Step 7 tests — cross-session aggregation.

Three trajectory cases assembled from synthetic digests (no LLM):
  1. stays_external: three sessions of mostly_external attribution
  2. shifts_internal: external → mixed → internal across three sessions
  3. drifts_off_topic: internal session, then derailed, then silent

Also: append/load round-trip against a tmp_path ledger, including the
guarantee that raw_transcript fields are never present in the persisted
record (they should have been guardrailed out before we ever reach
append_digest).
"""
from __future__ import annotations

import json

import pytest

from skills.interview_reflection.aggregate import (
    DEFAULT_STORAGE_ROOT,
    RECURRING_MIN_SESSIONS,
    append_digest,
    list_all_slugs,
    load_digests,
    load_latest_profile,
    load_latest_record,
    run_aggregate,
)


# --- helpers ---

def _digest(slug: str, themes: list[str], internal: float, external: float,
            session: int) -> dict:
    return {
        "submission_id": f"{slug}-s{session}",
        "interviewee_slug": slug,
        "themes": themes,
        "attribution_patterns": {"internal": internal, "external": external},
        "suggested_next_questions": [],
        "session_summary": f"session {session}",
        "ingest_timestamp": f"2026-05-{session+10:02d}T12:00:00+00:00",
    }


# --- round-trip persistence ---

def test_append_and_load_roundtrip(tmp_path):
    d1 = _digest("leo", ["shipping cadence"], 0.7, 0.3, 1)
    d2 = _digest("leo", ["shipping cadence", "outbound"], 0.8, 0.2, 2)

    append_digest("leo", d1, root=tmp_path)
    append_digest("leo", d2, root=tmp_path)

    loaded = load_digests("leo", root=tmp_path)
    assert len(loaded) == 2
    assert loaded[0]["submission_id"] == "leo-s1"
    assert loaded[1]["submission_id"] == "leo-s2"


def test_append_adds_timestamp_when_missing(tmp_path):
    digest_no_ts = {
        "submission_id": "x",
        "interviewee_slug": "kai",
        "themes": [],
        "attribution_patterns": {"internal": 0.5, "external": 0.5},
    }
    append_digest("kai", digest_no_ts, root=tmp_path)
    loaded = load_digests("kai", root=tmp_path)
    assert loaded[0].get("ingest_timestamp")


def test_load_returns_empty_for_unknown_slug(tmp_path):
    assert load_digests("never-existed", root=tmp_path) == []


# --- cross-person cohort readers (S7) ---

def _profile_digest(slug: str, building: str, session: int) -> dict:
    return {
        "submission_id": f"{slug}-s{session}",
        "interviewee_slug": slug,
        "collaboration_profile": {"building": building, "offers": [], "needs": []},
        "rubric_panel": {},
    }


def test_list_all_slugs_finds_seeded_files(tmp_path):
    append_digest("leo", _profile_digest("leo", "payments app", 1), root=tmp_path)
    append_digest("mira", _profile_digest("mira", "infra tool", 1), root=tmp_path)
    assert list_all_slugs(root=tmp_path) == ["leo", "mira"]


def test_list_all_slugs_empty_when_no_dir(tmp_path):
    assert list_all_slugs(root=tmp_path / "nope") == []


def test_load_latest_record_returns_last(tmp_path):
    append_digest("leo", _profile_digest("leo", "first", 1), root=tmp_path)
    append_digest("leo", _profile_digest("leo", "second", 2), root=tmp_path)
    rec = load_latest_record("leo", root=tmp_path)
    assert rec["submission_id"] == "leo-s2"
    assert load_latest_record("ghost", root=tmp_path) is None


def test_load_latest_profile_returns_most_recent_profile(tmp_path):
    append_digest("leo", _profile_digest("leo", "old build", 1), root=tmp_path)
    append_digest("leo", _profile_digest("leo", "new build", 2), root=tmp_path)
    profile = load_latest_profile("leo", root=tmp_path)
    assert profile["building"] == "new build"


def test_load_latest_profile_falls_back_past_profileless_record(tmp_path):
    append_digest("leo", _profile_digest("leo", "good build", 1), root=tmp_path)
    # a later record with no collaboration_profile (e.g. an old-shape entry)
    append_digest("leo", {"submission_id": "leo-s2", "interviewee_slug": "leo"}, root=tmp_path)
    profile = load_latest_profile("leo", root=tmp_path)
    assert profile is not None
    assert profile["building"] == "good build"


def test_load_latest_profile_none_when_no_profile(tmp_path):
    append_digest("kai", {"submission_id": "kai-s1", "interviewee_slug": "kai"}, root=tmp_path)
    assert load_latest_profile("kai", root=tmp_path) is None
    assert load_latest_profile("never", root=tmp_path) is None


# --- trajectory: stays external ---

def test_stays_external_trajectory():
    digests = [
        _digest("ada", ["reviewers blocking", "advisor slow"], 0.25, 0.75, 1),
        _digest("ada", ["reviewers blocking", "deadline slipping"], 0.30, 0.70, 2),
        _digest("ada", ["reviewers blocking", "advisor slow"], 0.20, 0.80, 3),
    ]
    out = run_aggregate(digests)
    assert out["session_count"] == 3
    assert out["attribution_trajectory"] == "stable_external"

    recurring_names = [r["theme"] for r in out["recurring_themes"]]
    assert "reviewers blocking" in recurring_names
    assert "advisor slow" in recurring_names


# --- trajectory: shifts internal ---

def test_shifts_internal_trajectory():
    digests = [
        _digest("mira", ["partner ghosting"], 0.2, 0.8, 1),
        _digest("mira", ["partner ghosting", "scheduling fix"], 0.5, 0.5, 2),
        _digest("mira", ["partner ghosting", "outbound cadence"], 0.8, 0.2, 3),
    ]
    out = run_aggregate(digests)
    assert out["attribution_trajectory"] == "shifted_internal"

    recurring_names = [r["theme"] for r in out["recurring_themes"]]
    assert "partner ghosting" in recurring_names

    # "outbound cadence" only in latest session — should show up as a new theme
    assert "outbound cadence" in out["new_themes"]


# --- trajectory: drifts off topic ---

def test_drifts_off_topic_trajectory():
    digests = [
        _digest("rune", ["reasoning evals", "milestone progress"], 0.7, 0.3, 1),
        _digest("rune", ["SAE distraction", "shiny object pattern"], 0.6, 0.4, 2),
        _digest("rune", [], 0.5, 0.5, 3),  # silent / no themes
    ]
    out = run_aggregate(digests)

    # No recurring themes — every theme only appeared once
    assert out["recurring_themes"] == []

    # Themes that appeared previously and not in latest session → dropped
    assert "reasoning evals" in out["dropped_themes"]
    assert "milestone progress" in out["dropped_themes"]
    assert "SAE distraction" in out["dropped_themes"]


# --- edge cases ---

def test_empty_history():
    out = run_aggregate([])
    assert out["session_count"] == 0
    assert out["attribution_trajectory"] == "insufficient_signal"
    assert out["recurring_themes"] == []


def test_single_session_is_insufficient_signal():
    digests = [_digest("solo", ["a theme"], 0.7, 0.3, 1)]
    out = run_aggregate(digests)
    assert out["attribution_trajectory"] == "insufficient_signal"
    assert out["session_count"] == 1


def test_themes_normalised_case_insensitively():
    digests = [
        _digest("x", ["Shipping Cadence"], 0.7, 0.3, 1),
        _digest("x", ["shipping cadence"], 0.7, 0.3, 2),
        _digest("x", ["SHIPPING CADENCE"], 0.7, 0.3, 3),
    ]
    out = run_aggregate(digests)
    assert len(out["recurring_themes"]) == 1
    assert out["recurring_themes"][0]["sessions"] == 3


def test_missing_attribution_patterns_does_not_crash():
    digests = [
        {"submission_id": "1", "themes": ["t"], "attribution_patterns": None},
        {"submission_id": "2", "themes": ["t"], "attribution_patterns": {}},
    ]
    out = run_aggregate(digests)
    assert out["attribution_trajectory"] == "insufficient_signal"
    assert out["recurring_themes"][0]["theme"] == "t"


def test_recurring_threshold_respected():
    digests = [
        _digest("y", ["once"], 0.5, 0.5, 1),
        _digest("y", ["once-also"], 0.5, 0.5, 2),
    ]
    out = run_aggregate(digests)
    # Neither theme appears in >= RECURRING_MIN_SESSIONS sessions
    assert out["recurring_themes"] == []
    assert RECURRING_MIN_SESSIONS == 2


# --- skill integration: persistence wired in ---

def test_skill_appends_to_ledger_on_run(tmp_path, monkeypatch):
    """End-to-end-ish: run_skill should append the guardrailed digest."""
    from types import SimpleNamespace
    from skills.interview_reflection import run_skill
    from skills.interview_reflection.models import TranscriptInput

    # Redirect the ledger to a tmp dir via monkeypatching the module constant
    import skills.interview_reflection.aggregate as agg_mod
    monkeypatch.setattr(agg_mod, "DEFAULT_STORAGE_ROOT", tmp_path)

    # Mock LLM so the agent returns predictable output (profile → rubric items)
    call_count = {"n": 0}

    def _stub(*_a, **_k):
        class _S:
            def invoke(self, _m):
                call_count["n"] += 1
                payload = (
                    {"building": "a thing", "building_tags": ["frontend"],
                     "offers": [{"text": "x", "tags": ["frontend"], "quote": "benign quote"}]}
                    if call_count["n"] % 2 == 1
                    else {"items": {f"CO{i}": {"score": 4, "quote": "ev"} for i in range(1, 6)}}
                )
                return SimpleNamespace(content=json.dumps(payload))
        return _S()
    monkeypatch.setattr("config.get_llm", _stub)

    run_skill([TranscriptInput(
        transcript="INTERVIEWER: hi\nINTERVIEWEE: I shipped a thing.",
        interviewee_slug="leo",
    )])

    loaded = load_digests("leo", root=tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["interviewee_slug"] == "leo"
    # Critical: raw transcript must NEVER reach the ledger
    assert "INTERVIEWEE:" not in json.dumps(loaded[0])
    assert "I shipped a thing" not in json.dumps(loaded[0])
