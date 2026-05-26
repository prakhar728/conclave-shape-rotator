"""
S4 tests — deterministic rubric aggregation (rubrics.aggregate_panel).

Pure code, no LLM. Confirms the universal aggregation rules from
instrument_registry_v0.md: quote-gated scoring, per-rubric minimums →
reported / "insufficient evidence", band labels, and PG3 fusion nulling.
"""
from __future__ import annotations

from skills.interview_reflection import rubrics


def _entry(score, quote="ev"):
    return {"score": score, "quote": quote}


def _full_coachability(score=4):
    return {f"CO{i}": _entry(score) for i in range(1, 6)}


def test_full_rubric_reports_mean_and_band():
    panel = rubrics.aggregate_panel(_full_coachability(score=4))
    co = panel.coachability
    assert co.reported is True
    assert co.score == 4.0
    assert co.band == "strong"
    assert len(co.items) == 5


def test_band_thresholds():
    low = rubrics.aggregate_panel({f"CO{i}": _entry(2) for i in range(1, 6)}).coachability
    assert low.band == "low"
    mixed = rubrics.aggregate_panel({f"CO{i}": _entry(3) for i in range(1, 6)}).coachability
    assert mixed.band == "mixed"


def test_below_minimum_is_unreported():
    # Coachability needs >=3 scored; give only 2.
    panel = rubrics.aggregate_panel({"CO1": _entry(4), "CO2": _entry(4)})
    co = panel.coachability
    assert co.reported is False
    assert co.score is None
    assert co.band is None


def test_score_without_quote_does_not_count():
    # 3 scores but one has no quote → only 2 count → below min(3) → unreported.
    items = {"CO1": _entry(4), "CO2": _entry(4), "CO3": {"score": 5, "quote": None}}
    co = rubrics.aggregate_panel(items).coachability
    assert co.reported is False
    # the unquoted item is retained for audit but nulled
    co3 = next(i for i in co.items if i.id == "CO3")
    assert co3.score is None


def test_out_of_range_score_ignored():
    items = {"CO1": _entry(9), "CO2": _entry(4), "CO3": _entry(4), "CO4": _entry(4)}
    co = rubrics.aggregate_panel(items).coachability
    # CO1=9 dropped; CO2..CO4 count → 3 scored, reported, mean 4.0
    assert co.reported is True
    assert co.score == 4.0


def test_agency_minimum_is_two():
    panel = rubrics.aggregate_panel({"LC1": _entry(5), "LC2": _entry(3)})
    assert panel.agency.reported is True
    assert panel.agency.score == 4.0


def test_pg3_is_nulled_and_excluded_from_progress_minimum():
    # PG1, PG2 scored (2 ≥ min 2) → reported; PG3 nulled regardless of input.
    items = {"PG1": _entry(4), "PG2": _entry(4), "PG3": _entry(5)}
    prog = rubrics.aggregate_panel(items).progress
    assert prog.reported is True
    assert prog.score == 4.0   # PG3 excluded from the mean
    pg3 = next(i for i in prog.items if i.id == "PG3")
    assert pg3.score is None and pg3.quote is None
    assert prog.contradiction_flag is None


def test_empty_input_all_unreported():
    panel = rubrics.aggregate_panel({})
    for rs in (panel.coachability, panel.agency, panel.proactivity,
               panel.goal_commitment, panel.progress):
        assert rs.reported is False
        assert rs.score is None


def test_non_dict_input_does_not_crash():
    panel = rubrics.aggregate_panel(None)  # type: ignore[arg-type]
    assert panel.coachability.reported is False


def test_format_items_for_prompt_lists_all_19():
    text = rubrics.format_items_for_prompt()
    for item_id in (["CO1", "CO2", "CO3", "CO4", "CO5", "LC1", "LC2", "LC3",
                     "PR1", "PR2", "PR3", "GC1", "GC2", "GC3", "GC4",
                     "PG1", "PG2", "PG3", "PG4"]):
        assert item_id in text
