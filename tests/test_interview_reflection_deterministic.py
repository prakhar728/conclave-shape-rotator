"""
Step 4 tests — Layer 1 (deterministic) against the full Step 3 fixture set.

Each fixture's `<slug>.expected.yaml` declares the bucket plus attribution-count
constraints. Constraints are intentionally loose (min / max / range) — the
deterministic layer is allowed to drift within those bands without failing the
build. Tightening happens after Step 10 (real-transcript iteration), not now.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from skills.interview_reflection.deterministic import run_deterministic


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "interview_reflection"


def _fixture_slugs() -> list[str]:
    return sorted(p.stem for p in FIXTURE_DIR.glob("*.txt"))


@pytest.mark.parametrize("slug", _fixture_slugs())
def test_fixture_matches_expected(slug):
    transcript = (FIXTURE_DIR / f"{slug}.txt").read_text()
    expected = yaml.safe_load((FIXTURE_DIR / f"{slug}.expected.yaml").read_text())

    out = run_deterministic(transcript)

    # 1. attribution bucket
    assert out["attribution_bucket"] == expected["attribution_bucket"], (
        f"{slug}: expected {expected['attribution_bucket']}, "
        f"got {out['attribution_bucket']} "
        f"(internal={out['internal_count']}, external={out['external_count']})"
    )

    # 2. attribution counts — loose constraints
    counts = expected.get("attribution_counts", {}) or {}
    if "internal_min" in counts:
        assert out["internal_count"] >= counts["internal_min"], (
            f"{slug}: internal {out['internal_count']} < min {counts['internal_min']}"
        )
    if "internal_max" in counts:
        assert out["internal_count"] <= counts["internal_max"], (
            f"{slug}: internal {out['internal_count']} > max {counts['internal_max']}"
        )
    if "external_min" in counts:
        assert out["external_count"] >= counts["external_min"], (
            f"{slug}: external {out['external_count']} < min {counts['external_min']}"
        )
    if "external_max" in counts:
        assert out["external_count"] <= counts["external_max"], (
            f"{slug}: external {out['external_count']} > max {counts['external_max']}"
        )
    if "internal_range" in counts:
        lo, hi = counts["internal_range"]
        assert lo <= out["internal_count"] <= hi, (
            f"{slug}: internal {out['internal_count']} outside [{lo}, {hi}]"
        )
    if "external_range" in counts:
        lo, hi = counts["external_range"]
        assert lo <= out["external_count"] <= hi, (
            f"{slug}: external {out['external_count']} outside [{lo}, {hi}]"
        )
    if counts.get("insufficient_signal_threshold_violated"):
        total = out["internal_count"] + out["external_count"]
        cap = counts.get("total_interviewee_pronouns_max", 6)
        assert total <= cap, (
            f"{slug}: total interviewee pronouns {total} > expected cap {cap}"
        )

    # 3. session word count within ±30% of fixture's documented approximation
    approx = expected.get("session_word_count_approx")
    if approx:
        lo, hi = int(approx * 0.7), int(approx * 1.3)
        assert lo <= out["session_word_count"] <= hi, (
            f"{slug}: word count {out['session_word_count']} outside ±30% of {approx}"
        )

    # 4. speaker turns > 0 unless edge_silent (which still has turns, just short)
    assert out["speaker_turn_count"] > 0


def test_run_deterministic_is_pure():
    """Same input → identical output. No hidden state."""
    t = "INTERVIEWER: Hi.\nINTERVIEWEE: I shipped a thing today. I think they liked it."
    a = run_deterministic(t)
    b = run_deterministic(t)
    assert a == b


def test_empty_transcript_returns_insufficient_signal():
    out = run_deterministic("")
    assert out["attribution_bucket"] == "insufficient_signal"
    assert out["internal_count"] == 0
    assert out["external_count"] == 0
    assert out["speaker_turn_count"] == 0
