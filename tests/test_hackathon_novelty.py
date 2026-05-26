import numpy as np
from unittest.mock import patch
from core.models import OperatorConfig
from skills.hackathon_novelty.models import HackathonSubmission
from skills.hackathon_novelty.deterministic import (
    fuse_text,
    compute_embeddings,
    pairwise_similarity,
    compute_novelty_scores,
    compute_percentiles,
    cluster_submissions,
    run_deterministic,
)
from tests.fixtures import FAKE_SUBMISSIONS


def _make_submissions() -> list[HackathonSubmission]:
    return [HackathonSubmission(**s) for s in FAKE_SUBMISSIONS]


def test_fuse_text_returns_idea_only():
    s = HackathonSubmission(submission_id="x", idea_text="idea", repo_summary="repo", deck_text="deck")
    assert fuse_text(s) == "idea"


def test_compute_embeddings_shape():
    texts = ["hello world", "foo bar", "test test"]
    emb = compute_embeddings(texts)
    assert emb.shape[0] == 3
    assert emb.shape[1] > 0


def test_pairwise_similarity_symmetric():
    emb = compute_embeddings(["hello", "world"])
    sim = pairwise_similarity(emb)
    assert abs(sim[0][1] - sim[1][0]) < 1e-6


def test_novelty_scores_bounded():
    sim = np.array([[1.0, 0.5], [0.5, 1.0]])
    scores = compute_novelty_scores(sim)
    assert all(0.0 <= s <= 1.0 for s in scores)


def test_percentiles_bounded():
    scores = np.array([0.2, 0.8, 0.5])
    pcts = compute_percentiles(scores)
    assert all(0.0 <= p <= 100.0 for p in pcts)


def test_cluster_returns_labels_for_each():
    emb = compute_embeddings(["a", "b", "c", "d", "e"])
    labels = cluster_submissions(emb)
    assert len(labels) == 5
    assert all(isinstance(l, str) for l in labels)


def test_run_deterministic_end_to_end():
    subs = _make_submissions()
    result = run_deterministic(subs)
    assert result["novelty_scores"].shape[0] == len(subs)
    assert result["percentiles"].shape[0] == len(subs)
    assert len(result["clusters"]) == len(subs)
    assert len(result["submission_ids"]) == len(subs)
    assert "relevance_scores" not in result


# --- Ingestion tests ---

from skills.hackathon_novelty.tools import get_raw_text, parse_markdown, set_context as _set_tool_context
from skills.hackathon_novelty.ingest import _parse_ingest_output


def test_ingest_passthrough():
    """Short plain text should pass through get_raw_text unchanged."""
    subs = [HackathonSubmission(submission_id="x", idea_text="A short idea about AI.")]
    import skills.hackathon_novelty.tools as tools_mod
    tools_mod._submissions = {s.submission_id: s for s in subs}
    result = get_raw_text.invoke({"submission_id": "x"})
    assert result["text"] == "A short idea about AI."
    assert result["word_count"] == 5


def test_ingest_markdown_strip():
    """Markdown formatting should be stripped to plain text."""
    subs = [HackathonSubmission(
        submission_id="md1",
        idea_text="# Title\n\n**Bold** and *italic* text with `code`.",
        idea_file_type="markdown",
    )]
    import skills.hackathon_novelty.tools as tools_mod
    tools_mod._submissions = {s.submission_id: s for s in subs}
    result = parse_markdown.invoke({"submission_id": "md1"})
    assert "#" not in result["text"]
    assert "**" not in result["text"]
    assert "*" not in result["text"]
    assert "`" not in result["text"]
    assert "Bold" in result["text"]
    assert "italic" in result["text"]


def test_ingest_parse_output():
    """Parser should extract valid submission_id → text mapping."""
    subs = [HackathonSubmission(submission_id="s1", idea_text="x")]
    text = '{"s1": "normalized text", "s2": "unknown id"}'
    result = _parse_ingest_output(text, subs)
    assert result == {"s1": "normalized text"}
    assert "s2" not in result


# --- Agent + Guardrails tests ---

from skills.hackathon_novelty import run_skill
from skills.hackathon_novelty.guardrails import HackathonNoveltyFilter


def test_run_skill_with_mocked_llm():
    """Full pipeline test — mock the LLM, verify output structure."""
    subs = _make_submissions()
    config = OperatorConfig(
        criteria={"originality": 0.4, "feasibility": 0.3, "impact": 0.3},
        guidelines="Focus on AI/ML innovations",
    )

    fake_agent_results = [
        {"submission_id": s.submission_id, "criteria_scores": {"originality": 7.0, "feasibility": 6.0, "impact": 8.0}, "aligned": True}
        for s in subs
    ]
    with patch("skills.hackathon_novelty.run_ingest", return_value={}), \
         patch("skills.hackathon_novelty.run_agent", return_value=fake_agent_results):
        response = run_skill(subs, config)

    assert response.skill == "hackathon_novelty"
    assert len(response.results) == len(subs)
    for r in response.results:
        assert "submission_id" in r
        assert 0.0 <= r["novelty_score"] <= 1.0
        assert "percentile" not in r
        assert "cluster" not in r
        assert "relevance_score" not in r
        assert "aligned" in r
        assert "criteria_scores" in r


def test_run_skill_marks_low_confidence_for_small_cohort():
    """Small cohorts (N < LOW_CONFIDENCE_THRESHOLD) get confidence='low'.
    The pipeline still runs end-to-end so early submitters see results
    even before more submissions land."""
    subs = [HackathonSubmission(submission_id="x", idea_text="test")]
    config = OperatorConfig(criteria={"originality": 1.0})
    response = run_skill(subs, config)
    assert response.results[0]["confidence"] == "low"


def test_filter_strips_extra_keys():
    f = HackathonNoveltyFilter()
    result = {"submission_id": "1", "novelty_score": 0.8, "secret_data": "leaked!", "internal_id": 42}
    filtered = f.filter_keys(result)
    assert "secret_data" not in filtered
    assert "internal_id" not in filtered
    assert filtered["submission_id"] == "1"


def test_filter_clamps_out_of_bounds():
    f = HackathonNoveltyFilter()
    result = {"novelty_score": 1.5, "criteria_scores": {"originality": 15.0}}
    clamped = f.check_bounds(result)
    assert clamped["novelty_score"] == 1.0
    assert clamped["criteria_scores"]["originality"] == 10.0


def test_filter_detects_leakage():
    f = HackathonNoveltyFilter()
    raw = "An AI-powered code review tool that uses LLMs to detect security vulnerabilities"
    result = {"submission_id": "1", "novelty_score": 0.8, "aligned": True, "criteria_scores": {raw[:30]: 5.0}}
    filtered = f.apply([result], [raw])
    assert "_leakage_warning" in filtered[0]
