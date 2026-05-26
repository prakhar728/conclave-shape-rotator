"""
S9 tests — orchestration (skill.run_matching) + the --match CLI demo.

LLM mocked (profile → rubric items → compose), embeddings forced to the hash
fallback. Ingests fixtures into a tmp ledger and checks the full path produces
non-empty intros and per-person panels.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from skills.interview_reflection import matching, run_skill
from skills.interview_reflection.aggregate import list_all_slugs, load_latest_record
from skills.interview_reflection.models import TranscriptInput
from skills.interview_reflection.skill import run_matching


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "interview_reflection"


@pytest.fixture(autouse=True)
def force_fallback_embeddings(monkeypatch):
    monkeypatch.setattr(matching, "_get_model", lambda: None)
    yield


@pytest.fixture
def mocked_llm(monkeypatch):
    """profile → rubric items → compose, cycled across get_llm() calls.

    Every person gets an offer AND a need on the same tag (frontend) plus a
    shared domain/stage, so cross-person help + peer intros are guaranteed.
    """
    n = {"i": 0}

    class _Stub:
        def invoke(self, _messages):
            n["i"] += 1
            phase = (n["i"] - 1) % 3
            if phase == 0:  # profile
                payload = {
                    "building": "a consumer payments app",
                    "building_tags": ["payments"],
                    "stage": "early-traction",
                    "offers": [{"text": "frontend onboarding", "tags": ["frontend"],
                                "quote": "I built the onboarding flow", "credibility": "demonstrated"}],
                    "needs": [{"text": "frontend polish", "tags": ["frontend"],
                               "quote": "I need help with the UI"}],
                }
            elif phase == 1:  # rubric items
                payload = {"items": {f"CO{i}": {"score": 4, "quote": "ev"} for i in range(1, 6)}}
            else:  # compose
                payload = {"rationale": {}, "summary": "Composed summary.", "bullets": []}
            return SimpleNamespace(content=json.dumps(payload))

    monkeypatch.setattr("config.get_llm", lambda *_a, **_k: _Stub())
    yield


def test_orchestration_ingest_then_match(tmp_path, mocked_llm):
    for slug, fx in [("leo", "prod_internal"), ("mira", "prod_external")]:
        transcript = (FIXTURE_DIR / f"{fx}.txt").read_text()
        run_skill([TranscriptInput(transcript=transcript, interviewee_slug=slug)],
                  ledger_root=tmp_path)

    # both persons have a profile + a reported rubric in the ledger
    assert set(list_all_slugs(tmp_path)) == {"leo", "mira"}
    for slug in ("leo", "mira"):
        rec = load_latest_record(slug, root=tmp_path)
        assert rec["collaboration_profile"]["building_tags"] == ["payments"]
        assert rec["rubric_panel"]["coachability"]["reported"] is True

    result = run_matching(root=tmp_path)
    assert result["intros"], "expected non-empty intros from complementary profiles"
    # a help intro carries both quotes
    helps = [i for i in result["intros"] if i["type"] == "help"]
    assert helps and helps[0]["quote_from"] and helps[0]["quote_to"]
    assert {n["slug"] for n in result["graph"]["nodes"]} == {"leo", "mira"}


def test_cli_match_smoke(monkeypatch, capsys, mocked_llm):
    from skills.interview_reflection import cli

    paths = [str(FIXTURE_DIR / "prod_internal.txt"), str(FIXTURE_DIR / "collab_internal.txt")]
    monkeypatch.setattr("sys.argv", ["cli", "--match", *paths])

    rc = cli.main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "RANKED INTROS" in out
    assert "PER-PERSON PANELS" in out
    # slugs resolved from the sibling .expected.yaml
    assert "LEO" in out and "SASHA" in out
