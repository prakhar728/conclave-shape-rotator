"""
Skill entry point for interview_reflection.

Per-person ingestion pipeline:
    1. deterministic.run_deterministic — pronoun counts, word count, keywords
    2. agent.run_agent                 — collaboration profile + rubric panel
                                         (+ composed rationale/summary/bullets, S5)
    3. guardrails.InterviewReflectionFilter — key whitelist, quote handling,
                                             name redaction, leakage check
    4. aggregate.append_digest         — per-slug ledger (cross-person matcher
                                         reads across slugs)

Cohort matching ("who should talk to whom") is a separate cross-person pass —
see run_matching, which reads the ledger the per-person path writes.

The interviewee-facing path (share_with_interviewee → IntervieweeOutput) is
retained as the seam for future role-based per-subject output; v1 is
organizer-only, so it carries no retired theme/ownership content.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from core.models import OperatorConfig, SkillResponse
from skills.interview_reflection.agent import run_agent
from skills.interview_reflection.aggregate import append_digest
from skills.interview_reflection.deterministic import run_deterministic
from skills.interview_reflection.guardrails import InterviewReflectionFilter
from skills.interview_reflection.models import (
    IntervieweeOutput,
    NovelOutput,
    TranscriptInput,
)


def run_skill(
    inputs: list[TranscriptInput],
    params: OperatorConfig | None = None,
    ledger_root: Optional[Path] = None,
) -> SkillResponse:
    """Run deterministic → agent → guardrails for each transcript in the batch.

    ledger_root overrides the per-slug ledger directory (used by the --match
    demo to ingest into a clean, reproducible root). Defaults to the standard
    data/ ledger when None.
    """
    results: list[dict] = []
    raw_transcripts: list[str] = []

    for sub in inputs:
        det = run_deterministic(sub.transcript)
        agent_out = run_agent(
            transcript=sub.transcript,
            interviewee_slug=sub.interviewee_slug,
            team_context={},
            deterministic=det,
        )

        novel = NovelOutput(
            submission_id=sub.submission_id,
            interviewee_slug=sub.interviewee_slug,
            collaboration_profile=agent_out["collaboration_profile"],
            rubric_panel=agent_out["rubric_panel"],
            rationale=agent_out["rationale"],
            summary=agent_out["summary"],
            bullets=agent_out["bullets"],
        )
        payload = novel.model_dump()
        # Carry share flag through so guardrails can gate the interviewee view.
        payload["share_with_interviewee"] = sub.share_with_interviewee

        if sub.share_with_interviewee:
            # Role-based per-subject view lands here later; organizer-only for now.
            interviewee = IntervieweeOutput(
                submission_id=sub.submission_id,
                interviewee_slug=sub.interviewee_slug,
            )
            payload["interviewee_output"] = interviewee.model_dump()

        results.append(payload)
        raw_transcripts.append(sub.transcript)

    filtered = InterviewReflectionFilter().apply(results, raw_transcripts)

    # Persist each guardrailed digest to the per-slug ledger. Persistence happens
    # AFTER guardrails so raw transcript text can never enter the ledger.
    for sub, digest in zip(inputs, filtered):
        if sub.interviewee_slug:
            append_digest(sub.interviewee_slug, digest, root=ledger_root)

    return SkillResponse(skill="interview_reflection", results=filtered)


def run_matching(root: Optional[Path] = None, top_k: Optional[int] = None) -> dict:
    """Cross-person cohort matching over the stored profiles (S8/S9)."""
    from skills.interview_reflection import matching
    return matching.run_matching(root=root, top_k=top_k)
