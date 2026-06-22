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
