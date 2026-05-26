"""
S5 tests — composition node (agent.compose_node + selection/fallback helpers).

OUT-1/2/3 are a view over the already-scored item layer: code selects which
items surface, the LLM only phrases, and a deterministic fallback covers the
offline path. Verifies traceability (no invented content), the
insufficient-evidence string for unreported rubrics, bullet selection, and that
the transcript is never handed to the compose LLM.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from skills.interview_reflection.agent import (
    INSUFFICIENT_EVIDENCE,
    _compose_fallback,
    _select_for_compose,
    compose_node,
)
from skills.interview_reflection import rubrics


def _panel_with(coachability_scores, agency_scores=None):
    raw = {f"CO{i}": {"score": s, "quote": f"co{i} quote"}
           for i, s in enumerate(coachability_scores, 1)}
    if agency_scores:
        raw.update({f"LC{i}": {"score": s, "quote": f"lc{i} quote"}
                    for i, s in enumerate(agency_scores, 1)})
    return rubrics.aggregate_panel(raw).model_dump()


PROFILE = {"building": "a payments app", "stage": "early-traction",
           "offers": [{"text": "frontend"}], "needs": [{"text": "sales"}]}


# --- selection ---

def test_selection_surfaces_only_scored_items_and_bullets():
    panel = _panel_with([5, 4, 3, 2, 1])  # all 5 coachability scored
    sel = _select_for_compose(panel, PROFILE)
    co = next(r for r in sel["rubrics"] if r["key"] == "coachability")
    assert co["reported"] is True
    assert len(co["evidence"]) == 5
    # highlights are the highest scored, watch the lowest, no overlap
    assert sel["highlights"][0]["score"] == 5
    hi_ids = {e["id"] for e in sel["highlights"]}
    assert all(w["id"] not in hi_ids for w in sel["watch"])
    assert sel["profile"]["building"] == "a payments app"


# --- fallback ---

def test_fallback_unreported_rubric_is_insufficient():
    panel = _panel_with([5, 4])  # 2 < min 3 → unreported
    sel = _select_for_compose(panel, PROFILE)
    out = _compose_fallback(sel)
    assert out["rationale"]["coachability"] == INSUFFICIENT_EVIDENCE


def test_fallback_reported_rationale_carries_quote():
    panel = _panel_with([5, 4, 4])  # reported
    sel = _select_for_compose(panel, PROFILE)
    out = _compose_fallback(sel)
    assert out["rationale"]["coachability"].startswith("Coachability:")
    assert "'co1 quote'" in out["rationale"]["coachability"]   # top-scored item's quote
    assert len(out["bullets"]) <= 6
    assert out["bullets"], "expected at least one bullet"


# --- node: model phrasing overlays, transcript never sent ---

def test_compose_node_uses_model_phrasing_for_reported(monkeypatch):
    captured = {}

    class _S:
        def invoke(self, messages):
            captured["human"] = messages[-1].content
            return SimpleNamespace(content=json.dumps({
                "rationale": {"coachability": "Coachability: strong — phrased by model ('co1 quote')"},
                "summary": "A model-written summary.",
                "bullets": ["✓ model bullet ('co1 quote')"],
            }))
    monkeypatch.setattr("config.get_llm", lambda *_a, **_k: _S())

    state = {"rubric_panel": _panel_with([5, 4, 4]), "collaboration_profile": PROFILE}
    out = compose_node(state)
    assert out["rationale"]["coachability"] == "Coachability: strong — phrased by model ('co1 quote')"
    assert out["summary"] == "A model-written summary."
    assert out["bullets"] == ["✓ model bullet ('co1 quote')"]
    # the transcript is never passed to the compose model — only the selection
    assert "<transcript>" not in captured["human"]
    assert "INTERVIEWEE" not in captured["human"]


def test_compose_node_falls_back_when_llm_down(monkeypatch):
    def _boom(*_a, **_k):
        raise RuntimeError("offline")
    monkeypatch.setattr("config.get_llm", _boom)

    state = {"rubric_panel": _panel_with([5, 4, 4]), "collaboration_profile": PROFILE}
    out = compose_node(state)
    assert out["rationale"]["coachability"].startswith("Coachability:")
    assert out["summary"]
    assert out["bullets"]


def test_compose_node_unreported_stays_insufficient_even_if_model_invents(monkeypatch):
    """A model trying to phrase an unreported rubric must be ignored."""
    class _S:
        def invoke(self, _m):
            return SimpleNamespace(content=json.dumps({
                "rationale": {"coachability": "Coachability: strong — INVENTED"},
                "summary": "x", "bullets": [],
            }))
    monkeypatch.setattr("config.get_llm", lambda *_a, **_k: _S())

    state = {"rubric_panel": _panel_with([5, 4]), "collaboration_profile": PROFILE}  # unreported
    out = compose_node(state)
    assert out["rationale"]["coachability"] == INSUFFICIENT_EVIDENCE
