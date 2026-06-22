"""Part 1 increment 5 — candidate-detection MECHANICS (deterministic, default gate).

Monkeypatches `candidate.spacy_pass` so the seam + downstream wiring are tested
without the 15 MB model. 5a: the model + the monkeypatch seam. (5b/5c add state
assignment, run-once timing, and annotation shape.)
"""
from __future__ import annotations

import transcripts.candidate as cand


def test_candidate_span_defaults():
    s = cand.CandidateSpan(token_start=3, token_end=5, surface="DStack protocol")
    assert s.state == "candidate"
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


def test_assign_states_known_candidate_oov():  # CD-20 (real wordfreq + vocab, no spaCy)
    from transcripts import vocab
    tokens = ["the", "DStack", "protocol", "and", "the", "roadmap", "for", "Xyzzqq"]
    spans = [
        cand.CandidateSpan(token_start=1, token_end=3, surface="DStack protocol"),
        cand.CandidateSpan(token_start=5, token_end=6, surface="roadmap"),
        cand.CandidateSpan(token_start=7, token_end=8, surface="Xyzzqq"),
    ]
    vocab.put("u_cd20", "DStack protocol", type="project")  # make it known
    out = cand.assign_states(tokens, spans, "u_cd20")
    assert out[0].state == "known" and out[0].type == "project"  # vocab wins
    assert out[1].state == "candidate"  # English, not vocab
    assert out[2].state == "oov"  # not English, not vocab


def test_oov_two_payoffs():  # CD-27
    tokens = ["met", "Recato", "about", "Zzqqxv"]
    spans = [
        cand.CandidateSpan(token_start=1, token_end=2, surface="Recato"),
        cand.CandidateSpan(token_start=3, token_end=4, surface="Zzqqxv"),
    ]
    out = cand.assign_states(tokens, spans, "u_cd27")  # empty vocab
    assert out[0].state == "oov" and out[1].state == "oov"  # novel entity + ASR garble
