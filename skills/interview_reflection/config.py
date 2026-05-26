"""
Skill-specific constants for interview_reflection.

What to edit here:
- ALLOWED_NOVEL_OUTPUT_KEYS / ALLOWED_INTERVIEWEE_OUTPUT_KEYS: whitelist for the
  guardrail layer.
- MAX_QUOTE_CHARS: hard upper bound on any single string in Novel-facing output.
  ~25 tokens ≈ 120 characters by the rough 5-chars-per-token heuristic. Anything
  longer is assumed to be a verbatim transcript quote and is redacted.
- MIN_LEAKAGE_SUBSTRING_LENGTH: smallest contiguous transcript chunk the leakage
  detector will redact when found inside any output. Smaller = more aggressive.
- COHORT_PEOPLE_SLUGS: known interviewee/team-member slugs from Shape Rotator OS
  `people/*.md`. Names not on this list get redacted from outputs. v0 ships a
  placeholder set; Step 8 wires the real lookup.

Per-node model overrides (env-driven, no code edits needed):
- CONCLAVE_INTERVIEW_DEFAULT_MODEL  fallback for any node
- CONCLAVE_INTERVIEW_THEMES_MODEL   theme extraction node only
- CONCLAVE_INTERVIEW_OWNERSHIP_MODEL  ownership / attribution node only

Default is Qwen3-30B-A3B-Instruct-2507 — a NearAI `Private` model that actually
exists in the catalog as of 2026-05-21. Avoid `Anonymised` models (Anthropic /
OpenAI / Google routed) for confidential data per [[project_nearai_models]].

Suggested presets:
  Dev / smoke tests       Qwen/Qwen3-30B-A3B-Instruct-2507   $0.15/$0.55
  Better quality          Qwen/Qwen3.5-122B-A10B             $0.40/$3.20
  Cheapest                google/gemma-4-31B-it              $0.13/$0.40

When CONCLAVE_LLM_BACKEND=ollama, these IDs are ignored — config.get_llm uses
settings.ollama_model uniformly so a single switch flips dev between cloud and
local without per-skill changes.

Consumed by guardrails.py, agent.py, and (via skill_card) __init__.py.
"""
from __future__ import annotations

import os


_DEFAULT_MODEL = (
    os.environ.get("CONCLAVE_INTERVIEW_DEFAULT_MODEL")
    or "Qwen/Qwen3-30B-A3B-Instruct-2507"
)
THEMES_MODEL: str = (
    os.environ.get("CONCLAVE_INTERVIEW_THEMES_MODEL") or _DEFAULT_MODEL
)
OWNERSHIP_MODEL: str = (
    os.environ.get("CONCLAVE_INTERVIEW_OWNERSHIP_MODEL") or _DEFAULT_MODEL
)
# Collaboration-matching + rubric-panel nodes (temp 0). Same default model;
# overridable per node via env for tuning without code edits.
PROFILE_MODEL: str = (
    os.environ.get("CONCLAVE_INTERVIEW_PROFILE_MODEL") or _DEFAULT_MODEL
)
RUBRIC_MODEL: str = (
    os.environ.get("CONCLAVE_INTERVIEW_RUBRIC_MODEL") or _DEFAULT_MODEL
)
COMPOSE_MODEL: str = (
    os.environ.get("CONCLAVE_INTERVIEW_COMPOSE_MODEL") or _DEFAULT_MODEL
)


ALLOWED_NOVEL_OUTPUT_KEYS: set[str] = {
    "submission_id",
    "interviewee_slug",
    "collaboration_profile",
    "rubric_panel",
    "rationale",
    "summary",
    "bullets",
}

ALLOWED_INTERVIEWEE_OUTPUT_KEYS: set[str] = {
    "submission_id",
    "interviewee_slug",
    "themes",
    "ownership_prompts",
    "evidence_quotes",
}

# Length caps. A string longer than its cap is assumed to be an accidental
# transcript dump and is redacted. With the matching vertical the real leakage
# defense is the substring scan below; the cap is a coarse secondary guard, so a
# single generous non-quote default suffices (3-5 sentence summaries, rationale
# lines, and bullets all fit comfortably under it; a full transcript paragraph
# does not).
DEFAULT_QUOTE_CAP: int = 500
FIELD_QUOTE_CAPS: dict[str, int] = {
    "summary": 500,
}

# Designated organizer-only evidence-quote fields. Values reached under one of
# these dict keys are intentional verbatim transcript spans: they are EXEMPT
# from the leakage redactor and name redaction (a quote may legitimately contain
# a name), and capped only against a runaway (non-span) dump. Everything else
# keeps full name redaction + leakage scanning. Raw FULL transcripts are still
# never persisted — only short spans ride along as quotes.
QUOTE_FIELD_KEYS: frozenset[str] = frozenset({"quote"})
QUOTE_FIELD_CAP: int = 300

# Legacy alias retained for any out-of-tree callers; not used by the filter.
MAX_QUOTE_CHARS: int = DEFAULT_QUOTE_CAP

# Smallest contiguous transcript substring the leakage detector treats as a leak.
# 60 chars ≈ 12 tokens — small enough to catch fragments, large enough to avoid
# false positives on common phrasing.
MIN_LEAKAGE_SUBSTRING_LENGTH: int = 60

# Placeholder cohort roster. Step 8 replaces with a real Shape Rotator OS
# `people/*.md` slug load.
COHORT_PEOPLE_SLUGS: set[str] = {
    "leo", "mira", "dax", "ren", "ada", "noor", "sasha", "yuki", "kai", "rune",
}
