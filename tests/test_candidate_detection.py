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


def test_oov_proper_noun_flagged():  # CD-5
    from transcripts.candidate import assign_states, spacy_pass
    tokens, spans = spacy_pass("we use Recato today")
    out = assign_states(tokens, spans, "u_cd5")
    recato = next((s for s in out if "Recato" in s.surface), None)
    assert recato is not None and recato.state == "oov"


def test_known_from_vocab():  # CD-6
    from transcripts import vocab
    from transcripts.candidate import assign_states, spacy_pass
    tokens, spans = spacy_pass("we use the DStack protocol")
    vocab.put("u_cd6", "the DStack protocol", type="project")
    out = assign_states(tokens, spans, "u_cd6")
    dp = next((s for s in out if "DStack" in s.surface), None)
    assert dp is not None and dp.state == "known" and dp.type == "project"


def test_candidate_when_in_dict_not_vocab():  # CD-7
    from transcripts.candidate import assign_states, spacy_pass
    tokens, spans = spacy_pass("we discussed the roadmap")
    out = assign_states(tokens, spans, "u_cd7")
    rm = next((s for s in out if "roadmap" in s.surface), None)
    assert rm is not None and rm.state == "candidate"
