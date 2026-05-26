"""
Eval submissions for live pipeline testing.

Round 1 — 5 core submissions (plain text, short, idea-only):
  eval_001: AI code review tool — strong, relevant, crowded space
  eval_002: PR security scanner — near-duplicate of 001 (tests duplicate detection)
  eval_003: TEE medical records — strong, unique domain (should score highest)
  eval_004: "An app that uses AI to help people." — vague, minimal effort
  eval_007: Recipe sharing app — off-topic for AI/ML hackathon

Coverage:
  - Duplicate pair: 001 + 002 (same domain, similar approach)
  - Quality spread: 003 (strong) vs 004 (vague) vs 007 (off-topic)
  - Relevance: 001-003 relevant, 004 borderline, 007 clearly off-topic
  - All under 300 words → ingestion should pass through unchanged

Not committed as pytest fixtures — used only by scripts/eval_pipeline.py.
"""

EVAL_SUBMISSIONS = [
    {
        "submission_id": "eval_001",
        "idea_text": (
            "An AI-powered code review tool that automatically analyzes pull requests for bugs, "
            "security vulnerabilities, and code quality issues. Uses a fine-tuned LLM to provide "
            "inline suggestions with explanations and severity ratings. The system learns from "
            "accepted and rejected suggestions to improve over time, building a per-repository "
            "model of what 'good code' looks like for that specific team."
        ),
        "repo_summary": None,
        "deck_text": None,
    },
    {
        "submission_id": "eval_002",
        "idea_text": (
            "AI-powered security scanner for pull requests that detects vulnerabilities and malicious "
            "code patterns. Integrates directly with GitHub Actions to automatically block merges "
            "that introduce security regressions. Unlike static analysis tools, it understands "
            "semantic context — e.g., it can detect that a new SQL query is constructed from "
            "user input three function calls away, even across file boundaries."
        ),
        "repo_summary": None,
        "deck_text": None,
    },
    {
        "submission_id": "eval_003",
        "idea_text": (
            "Secure multi-hospital medical records platform using Trusted Execution Environments (TEEs) "
            "to enable collaborative research across institutions without ever exposing raw patient data. "
            "Hospitals can run federated queries and analytics while keeping records fully encrypted. "
            "The system supports SQL-like aggregate queries (e.g., 'average blood pressure for diabetic "
            "patients aged 40-60') where the TEE computes the result and adds calibrated noise via "
            "differential privacy before returning it. Individual records never leave the enclave."
        ),
        "repo_summary": None,
        "deck_text": None,
    },
    {
        "submission_id": "eval_004",
        "idea_text": "An app that uses AI to help people.",
        "repo_summary": None,
        "deck_text": None,
    },
    {
        "submission_id": "eval_007",
        "idea_text": (
            "A recipe sharing app for home cooks that lets users upload photos of their dishes, "
            "share step-by-step cooking instructions, and follow other home chefs. Features include "
            "ingredient-based search, dietary restriction filters, and a weekly meal planner. "
            "Users can create shopping lists from selected recipes that auto-merge overlapping "
            "ingredients. Social features include commenting, recipe remixing (fork a recipe and "
            "modify it), and seasonal cooking challenges with community voting."
        ),
        "repo_summary": None,
        "deck_text": None,
    },
]

# Standard operator config for all eval runs
EVAL_CRITERIA = {"originality": 0.4, "feasibility": 0.3, "impact": 0.3}
EVAL_GUIDELINES = "Focus on technical innovation and real-world applicability in AI and machine learning."
