"""Part 1 increment 5 — candidate-detection MECHANICS (deterministic, default gate).

Monkeypatches `candidate.spacy_pass` so the seam + downstream wiring are tested
without the 15 MB model. 5a: the model + the monkeypatch seam. (5b/5c add state
assignment, run-once timing, and annotation shape.)
"""
from __future__ import annotations

import transcripts.candidate as cand


def test_candidate_span_defaults():
    s = cand.CandidateSpan(token_start=3, token_end=5, surface="DStack protocol")
    assert s.state == "oov"  # OOV-only: a detected span is oov until a vocab hit
    assert s.source == "nlp"
    assert s.type is None


def test_spacy_pass_is_monkeypatchable(monkeypatch):  # the deterministic seam
    def fake(text):
        return (["the", "DStack", "protocol"],
                [cand.CandidateSpan(token_start=1, token_end=3, surface="DStack protocol")])

    monkeypatch.setattr(cand, "spacy_pass", fake)
    tokens, spans = cand.spacy_pass("anything")
    assert tokens == ["the", "DStack", "protocol"]
    assert spans[0].surface == "DStack protocol"
    assert (spans[0].token_start, spans[0].token_end) == (1, 3)


def test_assign_states_known_override():  # CD-20 — vocab upgrades an OOV span to known
    from transcripts import vocab
    tokens = ["we", "use", "DStack", "and", "Xyzzqq"]
    spans = [  # OOV-only: spans arrive as oov; assign_states only flips vocab hits
        cand.CandidateSpan(token_start=2, token_end=3, surface="DStack", state="oov"),
        cand.CandidateSpan(token_start=4, token_end=5, surface="Xyzzqq", state="oov"),
    ]
    vocab.put("u_cd20", "DStack", type="project")  # previously tagged → known
    out = cand.assign_states(tokens, spans, "u_cd20")
    assert out[0].state == "known" and out[0].type == "project"  # vocab wins
    assert out[1].state == "oov"  # not vocab → stays oov


def test_oov_two_payoffs():  # CD-27
    tokens = ["met", "Recato", "about", "Zzqqxv"]
    spans = [
        cand.CandidateSpan(token_start=1, token_end=2, surface="Recato"),
        cand.CandidateSpan(token_start=3, token_end=4, surface="Zzqqxv"),
    ]
    out = cand.assign_states(tokens, spans, "u_cd27")  # empty vocab
    assert out[0].state == "oov" and out[1].state == "oov"  # novel entity + ASR garble


def _save_one(sid, text):
    from transcripts import store
    from transcripts.models import RawSegment, Session, SessionMetadata
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="s", text=text)],
        metadata=SessionMetadata(date="2026-06-22", source="t"),
    ))


def test_detect_runs_once_at_draft(monkeypatch):  # CD-22 (latency guard)
    from transcripts import store
    calls = {"n": 0}

    def spy(text, user_id):
        calls["n"] += 1
        return (text.split(), [])

    monkeypatch.setattr(cand, "detect", spy)
    _save_one("cd22", "hello world")
    store.create_v2_draft("cd22")
    assert calls["n"] == 1
    store.edit_token("cd22", 0, 0, "HELLO")
    store.edit_token("cd22", 0, 1, "WORLD")
    assert calls["n"] == 1  # edits do NOT re-run the pass


def test_draft_annotation_shape_and_raw_untouched(monkeypatch):  # CD-24/25
    from transcripts import store

    def fake(text, user_id):
        return (["the", "DStack", "protocol"],
                [cand.CandidateSpan(token_start=1, token_end=3, surface="DStack protocol", state="oov")])

    monkeypatch.setattr(cand, "detect", fake)
    _save_one("cd24", "the DStack protocol")
    v2 = store.create_v2_draft("cd24")
    assert v2.status == "draft"
    assert len(v2.annotations) == 1
    a = v2.annotations[0]
    assert a.source == "nlp" and a.state == "oov"
    assert (a.span.segment_id, a.span.token_start, a.span.token_end) == (0, 1, 3)
    assert store.load_session("cd24").raw_diarization[0].text == "the DStack protocol"  # raw untouched


def test_classify_correction_deterministic(monkeypatch):  # CD-11 default-gate (audit fix)
    # Patch the POS + OOV seams so the correction filter is guarded WITHOUT spaCy
    # (the requires_spacy tier is deselected in the prod/default gate).
    monkeypatch.setattr(cand, "reparse_token",
                        lambda t: {"protocol": "NOUN", "DStack": "PROPN", "there": "ADV"}.get(t, "X"))
    monkeypatch.setattr(cand, "_is_oov_token", lambda t: t == "Zzqqxv")
    assert cand.classify_correction("protocol") == "promote"  # NOUN
    assert cand.classify_correction("DStack") == "promote"     # PROPN
    assert cand.classify_correction("Zzqqxv") == "promote"     # OOV
    assert cand.classify_correction("there") == "text"         # ADV, not OOV → not promoted
