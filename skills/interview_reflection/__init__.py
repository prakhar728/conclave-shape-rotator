"""
interview_reflection — V3 Track A sub-agent (per-interview team-contextual labeling).

This is the v0 scaffold. Only the SkillCard + a stub run_skill exist today so the
/skills registry lists it and downstream steps (models, deterministic, agent,
guardrails, aggregation, MCP) can land one commit at a time per build_pipeline.md.

V2 (hackathon_novelty) is the architectural exemplar — same layout will be filled
in across Steps 2–9.
"""
from __future__ import annotations

from core.skill_card import SkillCard
from skills.interview_reflection.config import (
    ALLOWED_INTERVIEWEE_OUTPUT_KEYS,
    ALLOWED_NOVEL_OUTPUT_KEYS,
)
from skills.interview_reflection.models import TranscriptInput
from skills.interview_reflection.skill import run_skill


skill_card = SkillCard(
    name="interview_reflection",
    description=(
        "Per-interview team-contextual labeling for Shape Rotator cohort interviews. "
        "Inside the TEE: pulls team + person context, extracts themes, detects ownership "
        "vs. external attribution, and emits Novel-facing digests plus optional "
        "interviewee-facing self-awareness prompts. Raw transcripts never leave the enclave. "
        "v0 scaffold — pipeline layers land in subsequent build_pipeline.md steps."
    ),
    run=run_skill,
    input_model=TranscriptInput,
    output_keys=ALLOWED_NOVEL_OUTPUT_KEYS,
    user_output_keys=ALLOWED_INTERVIEWEE_OUTPUT_KEYS,
    config={},
    trigger_modes=[
        {
            "mode": "manual",
            "description": (
                "Novel (admin) submits an interview transcript; the pipeline runs on "
                "submission and returns a per-interviewee digest."
            ),
        },
    ],
    roles={
        "admin": {
            "description": (
                "Interviewer (Novel for Shape Rotator). Submits transcripts, sees all "
                "per-interviewee digests and cross-session deltas."
            ),
            "capabilities": ["submit", "view_all_results"],
        },
        "user": {
            "description": (
                "Interviewee. Sees only their own IntervieweeOutput, and only when the "
                "interviewer opts in via share_with_interviewee."
            ),
            "capabilities": [],
            "result_view": "own",
        },
    },
    setup_prompt=(
        "This skill digests interview transcripts inside a TEE and returns team-contextual "
        "labels — themes, attribution patterns, alignment-to-stated-goals, suggested "
        "next questions. Raw transcripts never leave the enclave.\n\n"
        "v0 is a scaffold; full I/O models and pipeline layers ship in subsequent steps."
    ),
    user_display={},
)
