"""
Layer 1 — deterministic features for one interview transcript.

Pure Python, no LLM calls. Computes:

- attribution_bucket: mostly_internal | mostly_external | mixed | shifting |
                      insufficient_signal
- internal_count / external_count: pronoun tallies over interviewee turns only
- session_word_count: whole-transcript word count (proxy for length)
- speaker_turn_count: number of interviewee turns
- keyword_freq: top non-stopword content tokens across interviewee turns

The output of this layer is one input to the agent layer (Step 5) and the
guardrail layer (Step 6). It is also what the test suite asserts against the
`*.expected.yaml` companions in tests/fixtures/interview_reflection/.

Transcript format: lines beginning with `INTERVIEWEE:` and `INTERVIEWER:`
delimit turns. Continuation lines belong to the most recent speaker. The
parser ignores blank lines.

Pronoun lists are intentionally small for v0 — Step 10 (real transcripts)
is the time to expand or tune them.
"""
from __future__ import annotations

import re
from collections import Counter
from typing import Iterable


INTERNAL_TOKENS: frozenset[str] = frozenset({
    "i", "i'm", "i've", "i'd", "i'll",
    "me", "my", "mine",
    "we", "we're", "we've", "we'd", "we'll",
    "us", "our", "ours",
})

EXTERNAL_TOKENS: frozenset[str] = frozenset({
    "they", "they're", "they've", "they'd", "they'll",
    "them", "their", "theirs",
})

# Minimum interviewee pronoun count before a bucket can be assigned.
# Below this, the layer emits "insufficient_signal" and the agent layer should
# refuse to fabricate themes.
INSUFFICIENT_SIGNAL_THRESHOLD: int = 6

# Share of (internal + external) that must be one side for "mostly_*".
DOMINANCE_THRESHOLD: float = 0.7

# Per-half share required to declare "shifting".
SHIFT_HALF_DOMINANCE: float = 0.6

# Minimum interviewee turns before half-split shifting detection is attempted.
MIN_TURNS_FOR_SHIFT: int = 4

_INTERVIEWEE_PREFIX: str = "INTERVIEWEE:"
_INTERVIEWER_PREFIX: str = "INTERVIEWER:"

_WORD_RE = re.compile(r"[A-Za-z']+")

_STOPWORDS: frozenset[str] = frozenset({
    "that", "this", "with", "have", "from", "what", "when", "then", "them",
    "than", "they", "would", "could", "should", "about", "there", "their",
    "been", "were", "your", "yours", "youre", "youve", "youd", "youll",
    "just", "like", "much", "more", "less", "some", "into", "very", "even",
    "also", "still", "going", "thing", "things", "stuff", "really", "kind",
    "sort", "well", "yeah", "okay", "right", "good", "bad", "out", "and",
    "the", "for", "but", "not", "you", "are", "was", "had", "has", "did",
    "does", "doing", "do", "got", "get", "getting", "make", "made", "say",
    "said", "saying", "tell", "told", "telling", "ask", "asked", "asking",
    "next", "last", "first", "second", "third", "today", "tomorrow",
    "yesterday", "week", "weeks", "month", "months", "year", "years",
    "morning", "afternoon", "evening", "lot", "bit", "little", "actually",
    "honestly", "maybe", "probably", "anyway", "though", "because", "since",
    "while", "where", "which", "whom", "whose",
})


def _tokens(text: str) -> list[str]:
    return [w.lower() for w in _WORD_RE.findall(text)]


def _interviewee_turns(transcript: str) -> list[str]:
    """Return only the interviewee's turns. Continuation lines without a
    speaker prefix are attached to the most recent speaker."""
    turns: list[str] = []
    speaker: str | None = None
    buf: list[str] = []
    for raw in transcript.splitlines():
        line = raw.rstrip()
        if line.startswith(_INTERVIEWEE_PREFIX):
            if speaker == "ee" and buf:
                turns.append(" ".join(buf).strip())
            speaker = "ee"
            buf = [line[len(_INTERVIEWEE_PREFIX):].strip()]
        elif line.startswith(_INTERVIEWER_PREFIX):
            if speaker == "ee" and buf:
                turns.append(" ".join(buf).strip())
            speaker = "er"
            buf = []
        else:
            if speaker == "ee":
                buf.append(line.strip())
    if speaker == "ee" and buf:
        turns.append(" ".join(buf).strip())
    return [t for t in turns if t]


def _count(tokens: Iterable[str], targets: frozenset[str]) -> int:
    return sum(1 for t in tokens if t in targets)


def _classify(interviewee_turns: list[str]) -> tuple[str, int, int]:
    full_tokens: list[str] = []
    for turn in interviewee_turns:
        full_tokens.extend(_tokens(turn))
    internal = _count(full_tokens, INTERNAL_TOKENS)
    external = _count(full_tokens, EXTERNAL_TOKENS)
    total = internal + external
    if total < INSUFFICIENT_SIGNAL_THRESHOLD:
        return "insufficient_signal", internal, external

    # Shifting detection — needs enough turns to split meaningfully.
    if len(interviewee_turns) >= MIN_TURNS_FOR_SHIFT:
        mid = len(interviewee_turns) // 2
        first = [t for turn in interviewee_turns[:mid] for t in _tokens(turn)]
        second = [t for turn in interviewee_turns[mid:] for t in _tokens(turn)]
        f_int, f_ext = _count(first, INTERNAL_TOKENS), _count(first, EXTERNAL_TOKENS)
        s_int, s_ext = _count(second, INTERNAL_TOKENS), _count(second, EXTERNAL_TOKENS)
        f_total, s_total = f_int + f_ext, s_int + s_ext
        if f_total >= 3 and s_total >= 3:
            f_ext_share = f_ext / f_total
            s_int_share = s_int / s_total
            f_int_share = f_int / f_total
            s_ext_share = s_ext / s_total
            if (f_ext_share >= SHIFT_HALF_DOMINANCE and s_int_share >= SHIFT_HALF_DOMINANCE):
                return "shifting", internal, external
            if (f_int_share >= SHIFT_HALF_DOMINANCE and s_ext_share >= SHIFT_HALF_DOMINANCE):
                return "shifting", internal, external

    if internal / total >= DOMINANCE_THRESHOLD:
        return "mostly_internal", internal, external
    if external / total >= DOMINANCE_THRESHOLD:
        return "mostly_external", internal, external
    return "mixed", internal, external


def _keyword_frequency(interviewee_turns: list[str], top_n: int = 10) -> dict[str, int]:
    tokens: list[str] = []
    for turn in interviewee_turns:
        tokens.extend(_tokens(turn))
    drop = INTERNAL_TOKENS | EXTERNAL_TOKENS | _STOPWORDS
    counts = Counter(t for t in tokens if len(t) > 3 and t not in drop)
    return dict(counts.most_common(top_n))


def run_deterministic(transcript: str) -> dict:
    """Compute Layer 1 features for one transcript. Pure function."""
    turns = _interviewee_turns(transcript)
    bucket, internal, external = _classify(turns)
    session_word_count = len(_tokens(transcript))
    return {
        "attribution_bucket": bucket,
        "internal_count": internal,
        "external_count": external,
        "session_word_count": session_word_count,
        "speaker_turn_count": len(turns),
        "keyword_freq": _keyword_frequency(turns),
    }
