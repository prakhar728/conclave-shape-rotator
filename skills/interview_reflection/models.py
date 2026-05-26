"""
Input and output Pydantic models for the interview_reflection skill.

These are the contract for the v0 pipeline (Pipeline A — per-interview team-contextual
labeling). Step 2 of build_pipeline.md establishes them as scaffolding; later steps
populate the values:

- Step 4 (deterministic): fills attribution_patterns and session-stat-derived fields
- Step 5 (agent):         fills themes, suggested_next_questions, session_summary,
                          ownership_prompts
- Step 6 (guardrails):    enforces output_keys; gates evidence_quotes on share_with_interviewee
- Step 7 (aggregation):   reads/writes per-slug digest history

Adding a field here AND to a future config.ALLOWED_OUTPUT_KEYS makes it flow through
the guardrail layer — mirrors the hackathon_novelty pattern.
"""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from core.models import Submission


class TranscriptInput(Submission):
    """One interview transcript submitted to the skill."""
    transcript: str
    interviewee_slug: str
    notes: Optional[str] = None                    # optional interviewer notes
    speaker_labels: Optional[list[str]] = None     # optional speaker turn labels
    share_with_interviewee: bool = False           # opt-in for IntervieweeOutput


class NovelOutput(BaseModel):
    """Interviewer-facing digest for one interview."""
    submission_id: str
    interviewee_slug: str
    themes: list[str] = Field(default_factory=list)
    attribution_patterns: dict[str, float] = Field(default_factory=dict)
    suggested_next_questions: list[str] = Field(default_factory=list)
    session_summary: str = ""


class IntervieweeOutput(BaseModel):
    """Interviewee-facing self-awareness payload — only emitted when
    TranscriptInput.share_with_interviewee=True. evidence_quotes stays empty otherwise."""
    submission_id: str
    interviewee_slug: str
    themes: list[str] = Field(default_factory=list)
    ownership_prompts: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
