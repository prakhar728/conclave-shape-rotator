"""Part 1 increment 5 — candidate detection with REAL spaCy (requires_spacy).

Structural assertions only (never pin exact NER labels). Auto-skipped where the
model isn't installed. 5a smoke; 5b/5c add OOV/state + correction-filter cases.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.requires_spacy


def test_noun_chunk_becomes_candidate():  # CD-1
    from transcripts.candidate import spacy_pass
    tokens, spans = spacy_pass("we use the DStack protocol")
    surfaces = [s.surface for s in spans]
    assert "the DStack protocol" in surfaces  # multi-word entity stays one span
    assert "we" not in surfaces  # pronoun-only chunk dropped (CD-3)


def test_span_anchors_align_with_tokens():
    from transcripts.candidate import spacy_pass
    tokens, spans = spacy_pass("we use the DStack protocol")
    sp = next(s for s in spans if s.surface == "the DStack protocol")
    # the token-relative anchor points at the same surface within `tokens`
    assert " ".join(tokens[sp.token_start:sp.token_end]) == "the DStack protocol"


def test_reparse_token_pos():
    from transcripts.candidate import reparse_token
    assert reparse_token("protocol") in ("NOUN", "PROPN")
    assert reparse_token("the") in ("DET", "PRON", "ADP")
