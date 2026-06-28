"""Candidate detection — the deterministic pass that flags words worth reviewing
(docs/plans/transcript-refine.md §15).

**OOV-only policy.** We highlight ONLY out-of-vocabulary tokens — words not in the
English frequency list, i.e. novel terms (Recato, DStack, TDX) or ASR garbles. Common
words and well-known entities (Google, "the meeting", "roadmap") are left alone: the
signal is deliberately rare and high-precision. The user tags high-value entities
manually during review; the LLM does the authoritative entity extraction post-approval
on the corrected text — not here.

**NER pre-typing (#7).** In the same spaCy pass, `doc.ents` are mapped to one of the
5 editor types (person/project/tech/affiliation/topic) and merged with OOV spans. NER
spans that overlap an OOV span on the same token range yield a single span carrying
both the OOV state and the NER type. NER spans for tokens that ARE in-vocabulary (e.g.
"Google") are added as typed candidate spans even though they are not OOV — the type is
the pre-fill. NER unavailable → no types (graceful; never raises).

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

#: A token with corpus frequency (wordfreq zipf) below this is out-of-vocabulary →
#: flagged. `< 1.0` catches anything appearing under ~1 per 10M words (invented names
#: + truly-rare terms) while staying well below common words (whose floor is ~3.0).
#: Tune toward ~1.5 to also catch rare tech acronyms (TDX 1.22, Phala 1.39) — see the
#: zipf sweep / `test_refine_full_smoke`.
OOV_ZIPF_MAX = 1.0

#: spaCy NER label → one of the 5 editor entity types.  Labels NOT in this map
#: are silently skipped (no span emitted for them).  See INCREMENT 2 spec.
_NER_TYPE_MAP: dict[str, str] = {
    "PERSON": "person",
    "ORG": "affiliation",
    "GPE": "affiliation",
    "LOC": "affiliation",
    "FAC": "affiliation",
    "NORP": "affiliation",
    "PRODUCT": "tech",
    "WORK_OF_ART": "topic",
    "EVENT": "topic",
    "LAW": "topic",
    "LANGUAGE": "topic",
}


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
    """An alphabetic token rare in the English frequency list (zipf < OOV_ZIPF_MAX) →
    out-of-vocab (a novel term or an ASR garble). Punctuation/numbers are not OOV
    signals."""
    t = tok.strip()
    if not t or not any(c.isalpha() for c in t):
        return False
    import wordfreq
    return wordfreq.zipf_frequency(t.lower(), "en") < OOV_ZIPF_MAX


def _oov_spans(tokens: list[str]) -> list[CandidateSpan]:
    """One candidate span per out-of-vocabulary token (token-relative anchor)."""
    return [
        CandidateSpan(token_start=i, token_end=i + 1, surface=tok, state="oov")
        for i, tok in enumerate(tokens)
        if _is_oov_token(tok)
    ]


def _ner_spans(doc, tokens: list[str]) -> list[CandidateSpan]:
    """Produce NER-typed candidate spans from `doc.ents`, using the same token
    list that `spacy_pass` returns.  Only labels in `_NER_TYPE_MAP` produce a
    span; others are silently skipped.  Graceful: any error → empty list."""
    try:
        spans: list[CandidateSpan] = []
        for ent in doc.ents:
            ent_type = _NER_TYPE_MAP.get(ent.label_)
            if ent_type is None:
                continue
            # ent.start / ent.end are token offsets into doc (same tokenization)
            surface = " ".join(tokens[ent.start:ent.end])
            spans.append(
                CandidateSpan(
                    token_start=ent.start,
                    token_end=ent.end,
                    surface=surface,
                    state="oov",  # upgraded by assign_states if vocab hit
                    type=ent_type,
                )
            )
        return spans
    except Exception:  # noqa: BLE001
        return []


def _merge_oov_ner(
    oov: list[CandidateSpan], ner: list[CandidateSpan]
) -> list[CandidateSpan]:
    """Merge OOV spans and NER spans into a deduplicated list.

    Merge rules:
    - If an NER span and an OOV span share exactly the same (token_start, token_end),
      keep ONE span: the OOV span's state + the NER span's type.
    - NER spans not overlapping any OOV span are added as-is (they bring typed
      annotation for in-vocabulary entities, e.g. "Google").
    - OOV spans with no matching NER span are kept as-is (type stays None).
    The result is sorted by token_start.
    """
    # Index OOV spans by (start, end)
    oov_by_range: dict[tuple[int, int], CandidateSpan] = {
        (s.token_start, s.token_end): s for s in oov
    }
    # Index NER spans by (start, end) for O(1) lookup
    ner_by_range: dict[tuple[int, int], CandidateSpan] = {
        (s.token_start, s.token_end): s for s in ner
    }

    merged: dict[tuple[int, int], CandidateSpan] = {}

    # Walk OOV spans: if NER covers the same range, inject the type
    for key, sp in oov_by_range.items():
        ner_sp = ner_by_range.get(key)
        if ner_sp is not None:
            merged[key] = sp.model_copy(update={"type": ner_sp.type})
        else:
            merged[key] = sp

    # Add NER spans that have NO matching OOV span
    for key, sp in ner_by_range.items():
        if key not in merged:
            merged[key] = sp

    return sorted(merged.values(), key=lambda s: s.token_start)


def spacy_pass(text: str) -> tuple[list[str], list[CandidateSpan]]:
    """Tokenize `text` (spaCy) and return (tokens, candidate spans).

    Spans come from two sources merged together:
    1. OOV-only: a span per out-of-vocabulary token (state='oov', type=None initially).
    2. NER pre-typing: entity spans from `doc.ents` with mapped type; merged with OOV
       so overlapping ranges produce one span carrying both OOV state and NER type.

    State is 'oov' here; the vocab 'known' upgrade happens in `assign_states`.
    """
    doc = _nlp()(text)
    tokens = [t.text for t in doc]
    oov = _oov_spans(tokens)
    ner = _ner_spans(doc, tokens)
    return tokens, _merge_oov_ner(oov, ner)


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
