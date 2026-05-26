"""
Skill entry point for interview_reflection (Track A v0).

Pipeline (current):
    1. deterministic.run_deterministic — pronoun counts, word count, keywords
    2. agent.run_agent                 — themes + ownership prompts (LangGraph + LLM)
    3. guardrails.InterviewReflectionFilter — key whitelist, quote stripping,
                                             evidence_quote gating, name redaction,
                                             leakage check

Team context lookup is stubbed in v0 — Step 8 wires it to Shape Rotator OS
`teams/<slug>.md`. For now it's an empty dict and the agent works without it.
"""
from __future__ import annotations

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


def run_skill(inputs: list[TranscriptInput], params: OperatorConfig | None = None) -> SkillResponse:
    """Run deterministic → agent → guardrails for each transcript in the batch."""
    results: list[dict] = []
    raw_transcripts: list[str] = []

    for sub in inputs:
        det = run_deterministic(sub.transcript)
        agent_out = run_agent(
            transcript=sub.transcript,
            interviewee_slug=sub.interviewee_slug,
            team_context={},  # Step 8 wires Shape Rotator OS lookup
            deterministic=det,
        )

        novel = NovelOutput(
            submission_id=sub.submission_id,
            interviewee_slug=sub.interviewee_slug,
            themes=agent_out["themes"],
            attribution_patterns=agent_out["attribution_patterns"],
            suggested_next_questions=agent_out["suggested_next_questions"],
            session_summary=agent_out["session_summary"],
        )
        payload = novel.model_dump()
        # Carry share flag through so guardrails can gate evidence_quotes.
        payload["share_with_interviewee"] = sub.share_with_interviewee

        if sub.share_with_interviewee:
            interviewee = IntervieweeOutput(
                submission_id=sub.submission_id,
                interviewee_slug=sub.interviewee_slug,
                themes=agent_out["themes"],
                ownership_prompts=agent_out["ownership_prompts"],
                evidence_quotes=[],  # populated only if Step 5 emits any; empty in v0
            )
            payload["interviewee_output"] = interviewee.model_dump()

        results.append(payload)
        raw_transcripts.append(sub.transcript)

    filtered = InterviewReflectionFilter().apply(results, raw_transcripts)

    # Persist each guardrailed digest to the per-slug ledger so Step 7's
    # aggregation has history to work with. Persistence happens AFTER
    # guardrails so raw transcript text can never enter the ledger.
    for sub, digest in zip(inputs, filtered):
        if sub.interviewee_slug:
            append_digest(sub.interviewee_slug, digest)

    return SkillResponse(skill="interview_reflection", results=filtered)
