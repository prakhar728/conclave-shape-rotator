"""C9 gate — golden-set runner + set-overlap metrics.

Asserts the contract documented in IMPLEMENTATION_PLAN.md §G10 / §H C9:

- Perfect match → 1.0 on every metric.
- Half-missed signals → 0.5 coverage.
- Spurious entities tank precision, missed entities tank recall.
- Baseline save/diff produces the deltas a prompt change has to move.

This file verifies the **metric**, not the model — synthetic Derived
objects against hand-built expected sets. Real-LLM eval is a separate
job (run via the `transcripts eval` CLI on top of `transcripts.cli enrich`).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from transcripts.eval import (
    EvalReport,
    SessionScore,
    _load_golden,
    _score,
    diff_baseline,
    save_baseline,
)
from transcripts.models import Derived, Entity, Signal


def _derived(*, signals: list[str], entities: list[str]) -> Derived:
    return Derived(
        summary="(synthetic)",
        signals=[Signal(kind="action_item", text=t) for t in signals],
        entities=[Entity(name=n, type="concept") for n in entities],
        graph_nodes=None,
    )


# ---------------------------------------------------------------------------
# _score — the actual metric
# ---------------------------------------------------------------------------

def test_perfect_match_scores_1_on_everything():
    d = _derived(signals=["ship matcher", "wire voxterm"], entities=["VoxTerm", "matcher"])
    expected = {"signals": ["ship matcher", "wire voxterm"], "entities": ["voxterm", "MATCHER"]}
    out = _score(d, expected)
    assert out.signal_coverage == 1.0
    assert out.entity_precision == 1.0
    assert out.entity_recall == 1.0
    assert out.entity_f1 == 1.0
    assert out.missing_signals == []
    assert out.missing_entities == []
    assert out.spurious_entities == []


def test_half_missed_signals_is_half_coverage():
    d = _derived(signals=["ship matcher"], entities=[])
    expected = {"signals": ["ship matcher", "wire voxterm"], "entities": []}
    out = _score(d, expected)
    assert out.signal_coverage == 0.5
    assert "wire voxterm" in out.missing_signals


def test_signal_text_match_is_normalized():
    """Casing and whitespace don't matter — same dedup key as the reducer."""
    d = _derived(signals=["  Ship   the   Matcher  "], entities=[])
    out = _score(d, {"signals": ["ship the matcher"], "entities": []})
    assert out.signal_coverage == 1.0


def test_spurious_entities_tank_precision():
    d = _derived(signals=[], entities=["voxterm", "made-up-thing"])
    expected = {"signals": [], "entities": ["voxterm"]}
    out = _score(d, expected)
    assert out.entity_precision == 0.5    # 1 hit, 2 extracted
    assert out.entity_recall == 1.0       # the real one was found
    assert "made-up-thing" in out.spurious_entities


def test_missed_entities_tank_recall():
    d = _derived(signals=[], entities=["voxterm"])
    expected = {"signals": [], "entities": ["voxterm", "matcher", "shape-ui"]}
    out = _score(d, expected)
    assert out.entity_precision == 1.0    # everything extracted was real
    assert out.entity_recall == round(1 / 3, 4)
    assert sorted(out.missing_entities) == ["matcher", "shape-ui"]


def test_f1_is_harmonic_mean():
    """F1 = 2pr/(p+r). At p=1.0, r=0.5: F1 = 2*0.5/1.5 = 0.6667."""
    d = _derived(signals=[], entities=["voxterm"])
    expected = {"signals": [], "entities": ["voxterm", "matcher"]}
    out = _score(d, expected)
    assert out.entity_precision == 1.0
    assert out.entity_recall == 0.5
    assert out.entity_f1 == round(2 * 1.0 * 0.5 / 1.5, 4)


def test_empty_expected_signals_treated_as_perfect_coverage():
    """A golden file that declares no signals shouldn't punish a session for finding some."""
    d = _derived(signals=["ship matcher"], entities=[])
    out = _score(d, {"signals": [], "entities": []})
    assert out.signal_coverage == 1.0


def test_empty_derived_against_real_expected_is_zero_everywhere():
    d = _derived(signals=[], entities=[])
    expected = {"signals": ["a"], "entities": ["b"]}
    out = _score(d, expected)
    assert out.signal_coverage == 0.0
    assert out.entity_precision == 0.0
    assert out.entity_recall == 0.0
    assert out.entity_f1 == 0.0


# ---------------------------------------------------------------------------
# Golden YAML loader
# ---------------------------------------------------------------------------

def test_load_golden_reads_expected_yaml_files(tmp_path):
    (tmp_path / "alpha.expected.yaml").write_text(
        "signals: [decide A, do B]\nentities: [project-x, voxterm]\n", encoding="utf-8",
    )
    (tmp_path / "beta.expected.yaml").write_text(
        "session_id: explicit-id\nsignals: [decide C]\nentities: [foo]\n", encoding="utf-8",
    )
    # A stray non-golden file is ignored.
    (tmp_path / "not-golden.txt").write_text("nope", encoding="utf-8")

    out = _load_golden(tmp_path)
    assert "alpha" in out
    assert out["alpha"]["signals"] == ["decide A", "do B"]
    assert "explicit-id" in out                # YAML override wins over filename
    assert out["explicit-id"]["signals"] == ["decide C"]


def test_load_golden_missing_dir_returns_empty(tmp_path):
    assert _load_golden(tmp_path / "nope") == {}


# ---------------------------------------------------------------------------
# Aggregate + baseline diff
# ---------------------------------------------------------------------------

def test_aggregate_averages_across_sessions():
    report = EvalReport(sessions=[
        SessionScore(session_id="a", signal_coverage=1.0, entity_precision=1.0,
                     entity_recall=1.0, entity_f1=1.0),
        SessionScore(session_id="b", signal_coverage=0.0, entity_precision=0.0,
                     entity_recall=0.0, entity_f1=0.0),
    ]).finalize()
    assert report.avg_signal_coverage == 0.5
    assert report.avg_entity_f1 == 0.5


def test_save_and_diff_baseline_round_trips(tmp_path):
    r1 = EvalReport(sessions=[
        SessionScore(session_id="a", signal_coverage=0.5, entity_precision=0.5,
                     entity_recall=0.5, entity_f1=0.5),
    ]).finalize()
    path = tmp_path / "baseline.json"
    save_baseline(r1, path)

    # A "second run" with better numbers.
    r2 = EvalReport(sessions=[
        SessionScore(session_id="a", signal_coverage=0.8, entity_precision=0.7,
                     entity_recall=0.9, entity_f1=0.79),
    ]).finalize()
    delta = diff_baseline(r2, path)
    assert delta["signal_coverage"]["prev"] == 0.5
    assert delta["signal_coverage"]["now"] == 0.8
    assert delta["signal_coverage"]["delta"] == 0.3


def test_diff_baseline_missing_file_warns_not_crashes(tmp_path):
    r = EvalReport(sessions=[]).finalize()
    out = diff_baseline(r, tmp_path / "absent.json")
    assert "warning" in out
