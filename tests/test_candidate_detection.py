"""Part 1 — OOV-only candidate detection with REAL spaCy (requires_spacy).

Only out-of-vocabulary words are flagged (novel terms / ASR garbles); common words and
well-known entities are left alone. Auto-skipped where the model isn't installed.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.requires_spacy


def test_oov_token_becomes_candidate():  # CD-1
    from transcripts.candidate import spacy_pass
    tokens, spans = spacy_pass("we use the DStack protocol")
    surfaces = [s.surface for s in spans]
    assert "DStack" in surfaces  # the novel token is flagged
    assert all(s.state == "oov" for s in spans)
    for common in ("we", "use", "the", "protocol"):  # common words NOT flagged
        assert common not in surfaces


def test_well_known_and_common_not_flagged():  # the over-tagging fix
    from transcripts.candidate import spacy_pass
    _, spans = spacy_pass("we discussed the roadmap with Google on Friday")
    # roadmap / Google / Friday are all valid English → nothing is flagged
    assert [s.surface for s in spans] == []


def test_span_anchor_aligns_with_token():
    from transcripts.candidate import spacy_pass
    tokens, spans = spacy_pass("we use the DStack protocol")
    sp = next(s for s in spans if s.surface == "DStack")
    assert tokens[sp.token_start:sp.token_end] == ["DStack"]


def test_reparse_token_pos():
    from transcripts.candidate import reparse_token
    assert reparse_token("protocol") in ("NOUN", "PROPN")
    assert reparse_token("the") in ("DET", "PRON", "ADP")


def test_oov_proper_noun_flagged():  # CD-5
    from transcripts.candidate import detect
    _, spans = detect("we use Recato today", "u_cd5")
    recato = next((s for s in spans if s.surface == "Recato"), None)
    assert recato is not None and recato.state == "oov"


def test_known_from_vocab():  # CD-6 — a tagged token is re-recognized as known
    from transcripts import vocab
    from transcripts.candidate import detect
    vocab.put("u_cd6", "Dstack", type="project")
    _, spans = detect("we use Dstack today", "u_cd6")
    dp = next((s for s in spans if s.surface.lower() == "dstack"), None)
    assert dp is not None and dp.state == "known" and dp.type == "project"


def test_common_noun_not_flagged():  # CD-7 (flipped) — "roadmap" is valid English
    from transcripts.candidate import detect
    _, spans = detect("we discussed the roadmap", "u_cd7")
    assert all(s.surface != "roadmap" for s in spans)


def test_classify_correction_promotes_noun_propn_oov():  # CD-10
    from transcripts.candidate import classify_correction
    assert classify_correction("protocol") == "promote"  # NOUN
    assert classify_correction("DStack") == "promote"     # OOV/PROPN
    assert classify_correction("Recato") == "promote"     # OOV


def test_classify_correction_grammar_is_text_only():  # CD-11/12
    from transcripts.candidate import classify_correction
    assert classify_correction("there") == "text"
    assert classify_correction("the") == "text"
    assert classify_correction("and") == "text"
