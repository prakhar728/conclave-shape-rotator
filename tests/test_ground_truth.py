"""Part 1 increment 6 — ground-truth writes (the flywheel): GT-1/2/3/5/6/7, CD-26.

Tag/correction → per-user vocab. The detection pass is stubbed (these test the
vocab-write wiring, not detection) so they run deterministically without spaCy.
"""
from __future__ import annotations

import pytest

from transcripts import candidate, ground_truth, store, vocab
from transcripts.models import RawSegment, Session, SessionMetadata


@pytest.fixture(autouse=True)
def _no_spacy(monkeypatch):
    monkeypatch.setattr(candidate, "detect", lambda text, user_id: (text.split(), []))


def _saved(sid):
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="s", text="we use the DStack protocol")],
        metadata=SessionMetadata(date="2026-06-22", source="t"),
    ))
    store.create_v2_draft(sid)


def test_tag_entity_writes_vocab_and_annotation():  # GT-1
    _saved("gt1")
    ground_truth.tag_entity("gt1", 0, 3, 5, "DStack protocol", "project", "u_gt1")
    e = vocab.get("u_gt1", "DStack protocol")
    assert e and e.is_entity and e.type == "project" and e.provenance == "user"
    v2 = store.load_v2("gt1")
    assert any(
        a.source == "user" and a.surface == "DStack protocol"
        and a.type == "project" and a.state == "known"
        for a in v2.annotations
    )


def test_human_type_overrides_nlp():  # GT-3 / CD-26
    _saved("gt3")
    vocab.put("u_gt3", "DStack protocol", type="concept", provenance="nlp")  # nlp guess
    ground_truth.tag_entity("gt3", 0, 3, 5, "DStack protocol", "project", "u_gt3")
    e = vocab.get("u_gt3", "DStack protocol")
    assert e.type == "project" and e.provenance == "user"  # human wins


def test_tag_entity_is_per_user():  # GT-6
    _saved("gt6")
    ground_truth.tag_entity("gt6", 0, 3, 5, "DStack protocol", "project", "uA")
    assert vocab.get("uB", "DStack protocol") is None


def test_retag_updates_single_entry():  # GT-7
    _saved("gt7")
    ground_truth.tag_entity("gt7", 0, 3, 5, "DStack protocol", "project", "u_gt7")
    ground_truth.tag_entity("gt7", 0, 3, 5, "DStack protocol", "company", "u_gt7")
    e = vocab.get("u_gt7", "DStack protocol")
    assert e.type == "company"
    assert len(vocab.list_for_user("u_gt7")) == 1  # no duplicate


def test_correct_word_promote_writes_vocab(monkeypatch):  # GT-2
    monkeypatch.setattr(candidate, "classify_correction", lambda t: "promote")
    _saved("gt2")
    assert ground_truth.correct_word("gt2", 0, 3, "Dstack", "u_gt2") == "promote"
    e = vocab.get("u_gt2", "Dstack")
    assert e and e.provenance == "correction"
    assert store.load_v2("gt2").segments[0].tokens[3] == "Dstack"  # edit applied


def test_correct_word_grammar_no_vocab(monkeypatch):  # GT-5
    monkeypatch.setattr(candidate, "classify_correction", lambda t: "text")
    _saved("gt5")
    assert ground_truth.correct_word("gt5", 0, 0, "We", "u_gt5") == "text"
    assert vocab.get("u_gt5", "We") is None  # grammar fix never enters vocab
    assert store.load_v2("gt5").segments[0].tokens[0] == "We"  # edit still applied


@pytest.mark.requires_spacy
def test_correct_word_real_filter():  # GT-2/GT-5 end-to-end (real POS/OOV)
    _saved("gt_real")
    assert ground_truth.correct_word("gt_real", 0, 3, "Recato", "u_real") == "promote"
    assert vocab.get("u_real", "Recato") is not None
    assert ground_truth.correct_word("gt_real", 0, 0, "there", "u_real2") == "text"
    assert vocab.get("u_real2", "there") is None
