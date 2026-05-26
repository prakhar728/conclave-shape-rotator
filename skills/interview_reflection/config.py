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


ALLOWED_NOVEL_OUTPUT_KEYS: set[str] = {
    "submission_id",
    "interviewee_slug",
    "themes",
    "attribution_patterns",
    "suggested_next_questions",
    "session_summary",
}

ALLOWED_INTERVIEWEE_OUTPUT_KEYS: set[str] = {
    "submission_id",
    "interviewee_slug",
    "themes",
    "ownership_prompts",
    "evidence_quotes",
}

# Per-field length caps. Any string field exceeding its cap is assumed to be
# a verbatim transcript slice and is redacted. Caps are tuned to the natural
# length of each field:
#   - themes:                    short noun phrases (3-8 words)  → ~120 chars
#   - suggested_next_questions:  one-sentence prompts            → ~240 chars
#   - ownership_prompts:         one-sentence gentle nudges      → ~240 chars
#   - session_summary:           1-2 sentences anchored to goals → ~400 chars
#   - evidence_quotes:           short transcript snippets       → ~300 chars
#                                (only emitted when share_with_interviewee=True)
FIELD_QUOTE_CAPS: dict[str, int] = {
    "themes": 120,
    "suggested_next_questions": 240,
    "ownership_prompts": 240,
    "session_summary": 400,
    "evidence_quotes": 300,
}
DEFAULT_QUOTE_CAP: int = 240

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
