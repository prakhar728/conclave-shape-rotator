"""Candidate detection — the deterministic pass that flags words worth reviewing
(docs/plans/transcript-refine.md §15).

**OOV-only policy.** We highlight ONLY out-of-vocabulary tokens — words not in the
English frequency list, i.e. novel terms (Recato, DStack, TDX) or ASR garbles. Common
words and well-known entities (Google, "the meeting", "roadmap") are left alone: the
signal is deliberately rare and high-precision. The user tags high-value entities
manually during review; the LLM does the authoritative entity extraction post-approval
on the corrected text — not here.

Isolated behind this one module so the deterministic test tier can monkeypatch
`spacy_pass`, and so detection degrades gracefully when spaCy is absent. The pass OWNS
tokenization: `spacy_pass` returns `(tokens, spans)` with token-relative anchors, so
the v2 layer stores these tokens and candidate anchors stay aligned with the editable
token list.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import BaseModel


class CandidateSpan(BaseModel):
    """A candidate detected in one segment's text. Token-relative anchor."""

    token_start: int
    token_end: int  # exclusive
    surface: str
    state: str = "oov"  # oov | known (assign_states upgrades vocab hits)
    type: Optional[str] = None
    source: str = "nlp"


@lru_cache(maxsize=1)
def _nlp():
    import spacy
    return spacy.load("en_core_web_sm")


def _is_oov_token(tok: str) -> bool:
    """An alphabetic token unknown to the English frequency list → out-of-vocab
    (a novel term or an ASR garble). Punctuation/numbers are not OOV signals."""
    t = tok.strip()
    if not t or not any(c.isalpha() for c in t):
        return False
    import wordfreq
    return wordfreq.zipf_frequency(t.lower(), "en") == 0.0


def _oov_spans(tokens: list[str]) -> list[CandidateSpan]:
    """One candidate span per out-of-vocabulary token (token-relative anchor)."""
    return [
        CandidateSpan(token_start=i, token_end=i + 1, surface=tok, state="oov")
        for i, tok in enumerate(tokens)
        if _is_oov_token(tok)
    ]


def spacy_pass(text: str) -> tuple[list[str], list[CandidateSpan]]:
    """Tokenize `text` (spaCy) and return (tokens, OOV candidate spans).

    OOV-only: a span is emitted for each out-of-vocabulary token. State is 'oov' here;
    the vocab 'known' upgrade happens in `assign_states`.
    """
    doc = _nlp()(text)
    tokens = [t.text for t in doc]
    return tokens, _oov_spans(tokens)


def reparse_token(token_text: str) -> str:
    """POS tag of a single edited token — drives the correction filter:
    NOUN/PROPN → promote to candidate/vocab; function/grammar → text-only."""
    doc = _nlp()(token_text)
    return doc[0].pos_ if len(doc) else "X"


def assign_states(
    tokens: list[str], spans: list["CandidateSpan"], user_id: str
) -> list[CandidateSpan]:
    """Upgrade an OOV span to **known** when its surface is in the user's vocab (carry
    its type — the flywheel re-recognizing what they tagged before); otherwise the span
    stays **oov**. The oov decision itself lives in `spacy_pass` (the OOV scan)."""
    from transcripts import vocab as vocab_mod

    out: list[CandidateSpan] = []
    for sp in spans:
        entry = vocab_mod.get(user_id, sp.surface)
        if entry is not None:
            out.append(sp.model_copy(update={"state": "known", "type": entry.type}))
        else:
            out.append(sp)
    return out


def detect(text: str, user_id: str) -> tuple[list[str], list[CandidateSpan]]:
    """The draft-time pass: tokenize + OOV spans + states, in one call so tokens and
    span anchors come from the SAME tokenization.

    Graceful: if spaCy/the model isn't available, fall back to whitespace tokens — OOV
    detection still works (it only needs wordfreq). If wordfreq is also absent, the
    editor still works, just without smart detection.
    """
    try:
        tokens, spans = spacy_pass(text)
    except Exception:  # noqa: BLE001 — spaCy/model absent → tokenize by whitespace
        tokens = text.split()
        try:
            spans = _oov_spans(tokens)
        except Exception:  # noqa: BLE001 — wordfreq also absent → no detection
            return tokens, []
    return tokens, assign_states(tokens, spans, user_id)


def classify_correction(token_text: str) -> str:
    """A corrected token: 'promote' (NOUN/PROPN/OOV → likely a graph-worthy entity;
    vocab write happens in the ground-truth step) vs 'text' (a function/grammar fix —
    do NOT add to vocab/graph). §15 correction filter."""
    if _is_oov_token(token_text):
        return "promote"
    return "promote" if reparse_token(token_text) in ("NOUN", "PROPN") else "text"
