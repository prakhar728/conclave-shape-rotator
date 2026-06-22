"""Part 1 increment 8a — insights stale-on-edit (the latency guard): IN-2/3/6.

The decisive guarantee: edits flip a flag, they do NOT recompute insights — no
LLM/embedding call fires per edit.
"""
from __future__ import annotations

import pytest

import transcripts.embed as embed_mod
import transcripts.enrich as enrich_mod
import transcripts.kb_extract as kbx
from transcripts import candidate, store
from transcripts.models import CandidateAnnotation, RawSegment, Session, SessionMetadata, TokenSpan


@pytest.fixture(autouse=True)
def _no_spacy(monkeypatch):
    monkeypatch.setattr(candidate, "detect", lambda text, user_id: (text.split(), []))


def _draft(sid):
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="s", text="we use the DStack protocol")],
        metadata=SessionMetadata(date="2026-06-22", source="t"),
    ))
    return store.create_v2_draft(sid)


@pytest.fixture
def llm_spies(monkeypatch):
    calls = {"enrich": 0, "extract": 0, "embed": 0}
    monkeypatch.setattr(enrich_mod, "enrich_session", lambda s: calls.__setitem__("enrich", calls["enrich"] + 1))
    monkeypatch.setattr(kbx, "extract_session", lambda sid: calls.__setitem__("extract", calls["extract"] + 1))
    monkeypatch.setattr(embed_mod, "embed_texts", lambda *a, **k: (calls.__setitem__("embed", calls["embed"] + 1), [])[1])
    return calls


def test_draft_not_stale_initially():
    _draft("in0")
    assert store.load_v2("in0").insights_stale is False


def test_edit_marks_stale():  # IN-2
    _draft("in2")
    store.edit_token("in2", 0, 3, "Dstack")
    assert store.load_v2("in2").insights_stale is True


def test_edit_fires_no_llm(llm_spies):  # IN-3 — the latency guard
    _draft("in3")
    store.edit_token("in3", 0, 3, "Dstack")
    store.add_annotation("in3", CandidateAnnotation(
        span=TokenSpan(segment_id=0, token_start=3, token_end=4), surface="Dstack", state="oov"))
    store.assign_speaker("in3", 0, "Alice")
    assert llm_spies == {"enrich": 0, "extract": 0, "embed": 0}


def test_multiple_edits_single_stale_no_llm(llm_spies):  # IN-6
    _draft("in6")
    for i in range(5):
        store.edit_token("in6", 0, 3, f"X{i}")
    assert store.load_v2("in6").insights_stale is True
    assert llm_spies["enrich"] == 0 and llm_spies["extract"] == 0 and llm_spies["embed"] == 0
