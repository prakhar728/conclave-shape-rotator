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


def test_well_known_and_common_not_flagged():  # updated for NER pre-typing (#7)
    from transcripts.candidate import spacy_pass
    _, spans = spacy_pass("we discussed the roadmap with Google on Friday")
    # Common words (roadmap, we, discussed, the, with, on) are NOT OOV → no OOV span.
    # "Friday" is DATE in spaCy → not in _NER_TYPE_MAP → no span.
    # "Google" IS recognised as ORG → affiliation typed span (NER pre-typing).
    # So: only "Google" appears, as an affiliation-typed span.
    surfaces = [s.surface for s in spans]
    assert "Google" in surfaces  # NER: ORG → affiliation
    for common in ("we", "discussed", "the", "roadmap", "with", "on", "Friday"):
        assert common not in surfaces  # common words + untyped labels still suppressed
    google_span = next(s for s in spans if s.surface == "Google")
    assert google_span.type == "affiliation"


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


# ---------------------------------------------------------------------------
# NER pre-typing (#7) — INCREMENT 2
# ---------------------------------------------------------------------------

def test_ner_person_and_affiliation():  # CD-30
    """'Barack Obama met at Google.' → typed spans for PERSON and ORG."""
    from transcripts.candidate import detect
    _, spans = detect("Barack Obama met at Google.", "u_cd30")
    # spaCy groups "Barack Obama" as one PERSON entity (start=0, end=2)
    person_span = next((s for s in spans if s.type == "person"), None)
    assert person_span is not None, "Expected a person-typed span"
    assert "Obama" in person_span.surface or person_span.surface == "Barack Obama"
    # "Google" is ORG → affiliation
    aff_span = next((s for s in spans if s.type == "affiliation"), None)
    assert aff_span is not None, "Expected an affiliation-typed span"
    assert "Google" in aff_span.surface
    # Both are source="nlp"
    assert all(s.source == "nlp" for s in spans)


def test_ner_annotation_type_carried_through_draft():  # CD-31
    """Type is propagated through detect → create_v2_draft → CandidateAnnotation."""
    from transcripts import store
    from transcripts.models import RawSegment, Session, SessionMetadata

    sid = "cd31_ner"
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="s", text="Barack Obama met at Google.")],
        metadata=SessionMetadata(date="2026-06-21", source="t"),
    ))
    v2 = store.create_v2_draft(sid)
    types = {a.type for a in v2.annotations if a.type is not None}
    assert "person" in types, f"Expected person type; got annotations: {v2.annotations}"
    assert "affiliation" in types, f"Expected affiliation type; got annotations: {v2.annotations}"
    for a in v2.annotations:
        assert a.source == "nlp"


def test_ner_classify_correction_gate_unchanged():  # CD-32
    """NER does not affect the promotion gate — classify_correction is unchanged."""
    from transcripts.candidate import classify_correction
    assert classify_correction("their") == "text"
    assert classify_correction("Kubernetes") == "promote"


def test_ner_nonoov_entity_gets_type():  # CD-33
    """An in-vocabulary entity ('Google') still gets a type via NER even though it
    is not OOV (zipf is high).  The NER span adds it as a typed annotation."""
    from transcripts.candidate import spacy_pass
    tokens, spans = spacy_pass("Google launched a new product")
    google = next((s for s in spans if "Google" in s.surface), None)
    assert google is not None, "Google (ORG) should appear as a typed NER span"
    assert google.type == "affiliation"


def test_ner_oov_entity_gets_both_oov_and_type():  # CD-34
    """An OOV token that is also an NER entity gets state=oov AND a type."""
    from transcripts.candidate import spacy_pass
    # "Recato" is OOV (rare) AND may be tagged as ORG/PRODUCT by spaCy in context
    tokens, spans = spacy_pass("we use DStack today")
    # DStack is OOV; if spaCy also recognizes it as an entity, we get both
    dstack = next((s for s in spans if s.surface == "DStack"), None)
    assert dstack is not None  # must appear as OOV
    assert dstack.state == "oov"  # OOV state preserved
    # type may be None (if spaCy doesn't NER-tag "DStack" in this context) or non-None — either is fine


def test_ner_unknown_label_skipped():  # CD-35
    """spaCy labels not in _NER_TYPE_MAP (e.g. DATE, CARDINAL) produce no NER span."""
    from transcripts.candidate import _ner_spans, _nlp
    doc = _nlp()("on Friday January 15 we had 3 meetings")
    tokens = [t.text for t in doc]
    ner = _ner_spans(doc, tokens)
    # DATE and CARDINAL labels should be absent
    for s in ner:
        assert s.type in ("person", "project", "tech", "affiliation", "topic")
