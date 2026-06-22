"""Candidate detection — the spaCy pass that finds entity candidates
(docs/plans/transcript-refine.md §15).

Isolated behind this one module so the deterministic test tier can monkeypatch
`spacy_pass` without the 15 MB model, and CI stays green without spaCy. v0:
noun-phrase candidates only; NER (`ent.label_` pre-typing) stays dormant for v1.

The pass OWNS tokenization: `spacy_pass` returns `(tokens, spans)` where spans are
token-relative to those tokens — so the v2 layer should store these tokens (5c),
keeping candidate anchors aligned with the editable token list.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from pydantic import BaseModel

#: POS tags whose chunks carry no entity signal — a noun_chunk made up only of
#: these (e.g. "we", "that thing") is dropped.
_FUNCTION_POS = {"PRON", "DET", "ADP", "CCONJ", "CONJ", "PART", "PUNCT", "SCONJ"}


class CandidateSpan(BaseModel):
    """A candidate detected in one segment's text. Token-relative anchor."""

    token_start: int
    token_end: int  # exclusive
    surface: str
    state: str = "candidate"  # known | candidate | oov (5b assigns)
    type: Optional[str] = None  # NER pre-type lands here in v1
    source: str = "nlp"


@lru_cache(maxsize=1)
def _nlp():
    import spacy
    return spacy.load("en_core_web_sm")


def spacy_pass(text: str) -> tuple[list[str], list[CandidateSpan]]:
    """Tokenize `text` and return (tokens, candidate spans).

    v0: each spaCy `noun_chunk` becomes a candidate span (token-relative), unless
    the whole chunk is function/pronoun words. State is left as 'candidate' here;
    5b assigns known/oov via the dictionary + vocab.
    """
    doc = _nlp()(text)
    tokens = [t.text for t in doc]
    spans: list[CandidateSpan] = []
    for chunk in doc.noun_chunks:
        if all(t.pos_ in _FUNCTION_POS for t in chunk):
            continue
        spans.append(
            CandidateSpan(
                token_start=chunk.start,
                token_end=chunk.end,
                surface=chunk.text,
            )
        )
    return tokens, spans


def reparse_token(token_text: str) -> str:
    """POS tag of a single edited token — drives the correction filter (5c):
    NOUN/PROPN → promote to candidate/vocab; function/grammar → text-only."""
    doc = _nlp()(token_text)
    return doc[0].pos_ if len(doc) else "X"


def _is_oov_token(tok: str) -> bool:
    """An alphabetic token unknown to the English frequency list → out-of-vocab
    (a novel term or an ASR garble). Punctuation/numbers are not OOV signals."""
    t = tok.strip()
    if not t or not any(c.isalpha() for c in t):
        return False
    import wordfreq
    return wordfreq.zipf_frequency(t.lower(), "en") == 0.0


def assign_states(
    tokens: list[str], spans: list["CandidateSpan"], user_id: str
) -> list[CandidateSpan]:
    """Assign each candidate a state (§15), per-user:

    - **known** — the surface is in the user's vocab → carry its type (wins even
      if the surface contains an OOV token, e.g. a confirmed "DStack protocol").
    - **oov** — contains a token unknown to English AND not vocab (novel entity
      or ASR error → highlight for review).
    - **candidate** — a recognized-English noun phrase, not yet in vocab.
    """
    from transcripts import vocab as vocab_mod

    out: list[CandidateSpan] = []
    for sp in spans:
        entry = vocab_mod.get(user_id, sp.surface)
        if entry is not None:
            out.append(sp.model_copy(update={"state": "known", "type": entry.type}))
            continue
        span_tokens = tokens[sp.token_start : sp.token_end]
        state = "oov" if any(_is_oov_token(t) for t in span_tokens) else "candidate"
        out.append(sp.model_copy(update={"state": state}))
    return out


def detect(text: str, user_id: str) -> tuple[list[str], list[CandidateSpan]]:
    """The draft-time pass: tokenize + candidate spans + states, in one call so
    tokens and span anchors come from the SAME tokenization.

    Graceful: if spaCy/the model isn't available (prod image keeps the deps out),
    fall back to whitespace tokens and no candidates — the editor still works,
    just without smart detection.
    """
    try:
        tokens, spans = spacy_pass(text)
    except Exception:  # noqa: BLE001 — spaCy/model absent → degrade, don't block
        return text.split(), []
    return tokens, assign_states(tokens, spans, user_id)


def classify_correction(token_text: str) -> str:
    """A corrected token: 'promote' (NOUN/PROPN/OOV → likely a graph-worthy
    entity; vocab write happens in the ground-truth step) vs 'text' (a function/
    grammar fix — do NOT add to vocab/graph). §15 correction filter."""
    if _is_oov_token(token_text):
        return "promote"
    return "promote" if reparse_token(token_text) in ("NOUN", "PROPN") else "text"
