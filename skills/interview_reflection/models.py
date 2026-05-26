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

from typing import Literal, Optional

from pydantic import BaseModel, Field

from core.models import Submission


# --- Collaboration profile (primary lead extraction) ---

class ProfileItem(BaseModel):
    """One offer / need / interest / seeking entry from a transcript.

    Every entry is quote-anchored: `quote` is a short verbatim transcript span
    that justifies the entry, or None. The profile node drops list entries that
    lack a quote (never invented). `credibility` is meaningful on offers only.
    """
    text: str
    tags: list[str] = Field(default_factory=list)              # normalized taxonomy tags
    quote: Optional[str] = None
    credibility: Optional[Literal["demonstrated", "claimed"]] = None


class CollaborationProfile(BaseModel):
    """Per-person collaboration profile — the matcher's primary input.

    Tags are normalized onto the closed taxonomy at extraction time; `stage` is
    one of taxonomy.STAGES (or None). See collaboration_matching_vertical.md §1.
    """
    building: Optional[str] = None
    building_tags: list[str] = Field(default_factory=list)
    offers: list[ProfileItem] = Field(default_factory=list)
    needs: list[ProfileItem] = Field(default_factory=list)
    interests: list[ProfileItem] = Field(default_factory=list)
    seeking: list[ProfileItem] = Field(default_factory=list)
    stage: Optional[str] = None


# --- Rubric panel (secondary personality signals) ---

class RubricItem(BaseModel):
    """One scored item of a rubric (e.g. CO1). score in 1..5 or None; every
    non-null score carries a verbatim evidence quote (instrument_registry_v0.md
    universal rules)."""
    id: str
    score: Optional[int] = None
    quote: Optional[str] = None


class RubricScore(BaseModel):
    """One rubric's aggregated result. `reported` is False when fewer than the
    rubric's minimum items are scored — surfaced as "insufficient evidence",
    a feature not a failure. `contradiction_flag` is progress-only (None in v1,
    no bound observed source)."""
    rubric: str
    score: Optional[float] = None
    band: Optional[str] = None                                 # "low" | "mixed" | "strong" | None
    reported: bool = False
    items: list[RubricItem] = Field(default_factory=list)
    contradiction_flag: Optional[bool] = None


class RubricPanel(BaseModel):
    """The five frozen instruments (instrument_registry_v0.md)."""
    coachability: RubricScore
    agency: RubricScore
    proactivity: RubricScore
    goal_commitment: RubricScore
    progress: RubricScore


class TranscriptInput(Submission):
    """One interview transcript submitted to the skill."""
    transcript: str
    interviewee_slug: str
    notes: Optional[str] = None                    # optional interviewer notes
    speaker_labels: Optional[list[str]] = None     # optional speaker turn labels
    share_with_interviewee: bool = False           # opt-in for IntervieweeOutput


class NovelOutput(BaseModel):
    """Interviewer-facing digest for one interview: collaboration profile +
    rubric panel + composed rationale/summary/bullets (the composition fields
    are populated by the compose node in S5)."""
    submission_id: str
    interviewee_slug: str
    collaboration_profile: Optional[CollaborationProfile] = None
    rubric_panel: Optional[RubricPanel] = None
    rationale: dict[str, str] = Field(default_factory=dict)    # OUT-1, per-rubric one-liners
    summary: str = ""                                          # OUT-2
    bullets: list[str] = Field(default_factory=list)           # OUT-3


class IntervieweeOutput(BaseModel):
    """Interviewee-facing self-awareness payload — only emitted when
    TranscriptInput.share_with_interviewee=True. evidence_quotes stays empty otherwise."""
    submission_id: str
    interviewee_slug: str
    themes: list[str] = Field(default_factory=list)
    ownership_prompts: list[str] = Field(default_factory=list)
    evidence_quotes: list[str] = Field(default_factory=list)
