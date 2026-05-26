"""
Layer 3 — output filter for interview_reflection.

Pipeline for each per-interview result:

    1. filter_keys     — drop anything outside the Novel/Interviewee whitelist
    2. strip_long_quotes — replace any single string > MAX_QUOTE_CHARS with [REDACTED LONG QUOTE]
    3. gate_evidence_quotes — drop evidence_quotes entirely when share_with_interviewee=False
    4. redact_unknown_names — replace capitalised names not in COHORT_PEOPLE_SLUGS with [REDACTED NAME]
    5. leakage_check   — final scan: any transcript substring >= MIN_LEAKAGE_SUBSTRING_LENGTH
                         present in serialised output gets replaced with [REDACTED]

The skill produces a payload of shape:

    {
      "submission_id": ...,
      "interviewee_slug": ...,
      "themes": [...],
      "attribution_patterns": {...},
      "suggested_next_questions": [...],
      "session_summary": "...",
      "interviewee_output": {  # only when share_with_interviewee=True
          "themes": [...],
          "ownership_prompts": [...],
          "evidence_quotes": [...],
      },
    }

The filter operates on this combined payload, applying ALLOWED_NOVEL_OUTPUT_KEYS
to the outer dict and ALLOWED_INTERVIEWEE_OUTPUT_KEYS to the nested
interviewee_output (when present).

Names policy:
A capitalised token (length >= 2) that is NOT in COHORT_PEOPLE_SLUGS (case-
insensitive) and NOT in PROTECTED_TOKENS is redacted. PROTECTED_TOKENS covers
common sentence starts and proper nouns we don't care about (days, months,
common product names). v0 is conservative; Step 10 (real transcripts) is the
right gate to retune the list against false positives.
"""
from __future__ import annotations

import re
from typing import Optional

from core.guardrails import LeakageDetector
from skills.interview_reflection.config import (
    ALLOWED_INTERVIEWEE_OUTPUT_KEYS,
    ALLOWED_NOVEL_OUTPUT_KEYS,
    COHORT_PEOPLE_SLUGS,
    DEFAULT_QUOTE_CAP,
    FIELD_QUOTE_CAPS,
    MIN_LEAKAGE_SUBSTRING_LENGTH,
)


PROTECTED_TOKENS: frozenset[str] = frozenset({
    # Sentence-start pronouns + articles
    "I", "I'm", "I've", "I'd", "I'll", "We", "We're", "We've",
    "You", "You're", "You've", "You'd", "You'll", "Your",
    "He", "She", "It", "They",
    "The", "A", "An",
    # Common starters / connectives
    "Yes", "No", "Maybe", "Honestly", "Anyway", "OK", "Okay", "Right", "Well",
    "But", "So", "Then", "Now", "Here", "There", "What", "Why",
    "How", "When", "Where", "Who", "Which", "That", "This", "These", "Those",
    "And", "Or", "Not", "If", "Else", "On", "In", "At", "For", "To",
    "Of", "By", "With", "From", "About", "Because", "Since", "While", "Until",
    # Modal + auxiliary verbs (the bug that triggered the rewrite — "Can you" was
    # being redacted as a name)
    "Can", "Could", "Would", "Should", "Will", "May", "Might", "Must", "Shall",
    "Have", "Has", "Had", "Having",
    "Do", "Does", "Did", "Doing", "Done",
    "Is", "Are", "Was", "Were", "Be", "Been", "Being", "Am",
    "Let", "Lets", "Let's",
    # Common high-frequency verbs at sentence starts
    "Make", "Makes", "Made", "Making",
    "Get", "Gets", "Got", "Getting",
    "Take", "Takes", "Took", "Taking", "Taken",
    "Go", "Goes", "Went", "Going", "Gone",
    "Come", "Comes", "Came", "Coming",
    "Say", "Says", "Said", "Saying",
    "Tell", "Tells", "Told", "Telling",
    "Ask", "Asks", "Asked", "Asking",
    "Think", "Thinks", "Thought", "Thinking",
    "Know", "Knows", "Knew", "Knowing", "Known",
    "Want", "Wants", "Wanted", "Wanting",
    "Need", "Needs", "Needed", "Needing",
    "Try", "Tries", "Tried", "Trying",
    "Walk", "Walks", "Walked", "Walking",
    "Tell", "Told", "Telling",
    # Days / months
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
    "January", "February", "March", "April", "May", "June", "July", "August",
    "September", "October", "November", "December",
    # Common product / company tokens that may appear in transcripts and don't
    # need redaction (extend in Step 10 against real transcripts).
    "Stripe", "Slack", "Twitter", "GCP", "P0", "CSV", "Loom",
    "Anthropic", "SAE", "MVP", "Tailwind",
    # Redaction sentinels — must not be name-redacted in subsequent passes.
    "REDACTED", "LONG", "QUOTE", "NAME",
})

_REDACTED_QUOTE = "[REDACTED LONG QUOTE]"
_REDACTED_NAME = "[REDACTED NAME]"
_REDACTED_LEAK = "[REDACTED]"

# Mid-sentence capitalised tokens are the real name signal. Sentence-initial
# capitalisation is normal English and produces nonstop false positives ("Outbound
# is the gap", "Will the block hold"). The lookbehind requires a lowercase letter
# or mid-sentence punctuation (`,`, `;`, `:`, `)`, quote) followed by whitespace
# immediately before the candidate. A token starting a new sentence (after `.!?`
# or string start) will NOT match.
#
# Tradeoff: a true name at the start of a sentence ("Eddie did not show up.")
# is missed. Acceptable for v0 — Step 10 (real transcripts) is the place to
# retune toward a name corpus or NER pass.
_NAME_TOKEN_RE = re.compile(r"(?<=[a-z,;:\)\'\"]\s)[A-Z][a-zA-Z'\-]+\b")


class InterviewReflectionFilter:
    def __init__(
        self,
        cohort_people: Optional[set[str]] = None,
        min_leakage_length: int = MIN_LEAKAGE_SUBSTRING_LENGTH,
        field_quote_caps: Optional[dict[str, int]] = None,
        default_quote_cap: int = DEFAULT_QUOTE_CAP,
    ):
        self.cohort_people = {s.lower() for s in (cohort_people if cohort_people is not None else COHORT_PEOPLE_SLUGS)}
        self.field_quote_caps = field_quote_caps if field_quote_caps is not None else FIELD_QUOTE_CAPS
        self.default_quote_cap = default_quote_cap
        self.leakage_detector = LeakageDetector(min_length=min_leakage_length)

    # --- public ---

    def apply(self, results: list[dict], raw_transcripts: list[str]) -> list[dict]:
        out: list[dict] = []
        for result in results:
            cleaned = self._apply_one(result, raw_transcripts)
            out.append(cleaned)
        return out

    # --- internals ---

    def _apply_one(self, result: dict, raw_transcripts: list[str]) -> dict:
        share = bool(result.get("share_with_interviewee"))
        nested = result.get("interviewee_output")

        outer = self._filter_keys(result, ALLOWED_NOVEL_OUTPUT_KEYS)
        outer = self._strip_long_quotes(outer)
        outer = self._redact_unknown_names(outer)

        if share and isinstance(nested, dict):
            inner = self._filter_keys(nested, ALLOWED_INTERVIEWEE_OUTPUT_KEYS)
            inner = self._strip_long_quotes(inner)
            inner = self._redact_unknown_names(inner)
            outer["interviewee_output"] = inner
        # else: nested dropped — evidence_quotes never leaves when share=False

        # Final leakage scan over the serialised payload.
        leakage = self.leakage_detector.check(str(outer), raw_transcripts)
        if leakage:
            outer = self._redact_leakage(outer, raw_transcripts)
            outer["_leakage_warning"] = f"Redacted {len(leakage)} leaked substring(s)"

        return outer

    def _filter_keys(self, payload: dict, allowed: set[str]) -> dict:
        return {k: v for k, v in payload.items() if k in allowed}

    def _strip_long_quotes(self, payload: dict) -> dict:
        cleaned = {}
        for k, v in payload.items():
            cap = self.field_quote_caps.get(k, self.default_quote_cap)
            cleaned[k] = self._strip_value(v, cap)
        return cleaned

    def _strip_value(self, v, cap: int):
        if isinstance(v, str):
            return _REDACTED_QUOTE if len(v) > cap else v
        if isinstance(v, list):
            return [self._strip_value(x, cap) for x in v]
        if isinstance(v, dict):
            return {k: self._strip_value(x, cap) for k, x in v.items()}
        return v

    def _redact_unknown_names(self, payload: dict) -> dict:
        cleaned = {}
        for k, v in payload.items():
            cleaned[k] = self._redact_names_in(v)
        return cleaned

    def _redact_names_in(self, v):
        if isinstance(v, str):
            return _NAME_TOKEN_RE.sub(self._maybe_redact_name, v)
        if isinstance(v, list):
            return [self._redact_names_in(x) for x in v]
        if isinstance(v, dict):
            return {k: self._redact_names_in(x) for k, x in v.items()}
        return v

    def _maybe_redact_name(self, m: re.Match) -> str:
        token = m.group(0)
        if token in PROTECTED_TOKENS:
            return token
        if token.lower() in self.cohort_people:
            return token
        return _REDACTED_NAME

    def _redact_leakage(self, payload: dict, raw_transcripts: list[str]) -> dict:
        cleaned = {}
        for k, v in payload.items():
            cleaned[k] = self._redact_leakage_value(v, raw_transcripts)
        return cleaned

    def _redact_leakage_value(self, v, raw_transcripts: list[str]):
        if isinstance(v, str):
            return self.leakage_detector.redact(v, raw_transcripts)
        if isinstance(v, list):
            return [self._redact_leakage_value(x, raw_transcripts) for x in v]
        if isinstance(v, dict):
            return {k: self._redact_leakage_value(x, raw_transcripts) for k, x in v.items()}
        return v
