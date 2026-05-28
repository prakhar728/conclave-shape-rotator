"""C8 gate — map-reduce enrichment + backfill pass.

Asserts the contract documented in IMPLEMENTATION_PLAN.md §G7 / §H C8:

- 1 chunk → single LLM call with the SINGLE prompt (the fast path).
- N chunks → N map calls + one reduce summary call; entity dedup by
  name and signal cap happen deterministically.
- ``enrich_pending`` skips on ``LLMUnavailable`` and continues the batch.
- Provenance is stamped on every successfully enriched session
  (``model_id``, ``enrich_prompt_version``, ``chunk_count``).

One opt-in ``@pytest.mark.requires_ollama`` test runs the full chunk →
map → reduce pipeline through the real local qwen2.5-conclave model on
a short cohort transcript; auto-skipped when Ollama isn't available.
"""
from __future__ import annotations

import json

import pytest

from storage import sqlite
from transcripts import store
from transcripts.enrich import (
    _dedup_entities,
    _dedup_signals,
    _reduce,
    enrich_pending,
    enrich_session,
    transcript_text,
)
from transcripts.llm import LLMUnavailable
from transcripts.models import (
    Derived,
    Entity,
    PIPELINE_VERSION,
    RawSegment,
    Session,
    SessionMetadata,
    Signal,
)
from transcripts.prompts import ENRICH_PROMPT_VERSION


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeLLM:
    """Returns one canned response per .invoke() call.

    ``responses`` is a list of JSON-serializable dicts; we serialize them
    on the way out so the parser exercises the same code path as a real model.
    Items can also be BaseException instances — those get raised.
    """

    model_name = "fake-llm"

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls: list[list] = []

    def invoke(self, messages):
        self.calls.append(list(messages))
        if not self._responses:
            raise AssertionError("FakeLLM ran out of canned responses")
        item = self._responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        body = item if isinstance(item, str) else json.dumps(item)
        return type("Resp", (), {"content": body})()


@pytest.fixture()
def tmp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(sqlite, "_DB_PATH", str(tmp_path / "t.db"))
    monkeypatch.setattr(sqlite, "_conn", None)
    sqlite.init_db()
    yield
    monkeypatch.setattr(sqlite, "_conn", None)


def _short_session() -> Session:
    """Small session — guaranteed to fit in one chunk."""
    return Session(
        session_id="short",
        raw_diarization=[
            RawSegment(speaker="Shaw", text="we should ship matching first", start=0.0),
            RawSegment(speaker="Alex", text="agreed, decision logged", start=4.0),
        ],
        metadata=SessionMetadata(date="2026-05-20", source="otter"),
    )


def _long_session() -> Session:
    """Forces multi-chunk path: many large segments above the chunk budget."""
    body = "word " * 2400  # ~3000 tokens each — three of these blow past 6000
    segs = [
        RawSegment(speaker=f"speaker_{i % 2}", text=f"{i}: {body}", start=float(i))
        for i in range(5)
    ]
    return Session(
        session_id="long",
        raw_diarization=segs,
        metadata=SessionMetadata(date="2026-05-20", source="otter"),
    )


# ---------------------------------------------------------------------------
# Single-chunk path
# ---------------------------------------------------------------------------

def test_single_chunk_uses_one_llm_call_and_stamps_provenance():
    sess = _short_session()
    fake = FakeLLM({
        "summary": "short meeting",
        "signals": [{"kind": "decision", "text": "ship matching first", "said_by": ["Shaw"]}],
        "entities": [{"name": "matching", "type": "project", "evidence": "main topic"}],
    })

    enrich_session(sess, llm=fake)

    assert len(fake.calls) == 1  # single-shot path — no reduce
    assert sess.derived.summary == "short meeting"
    assert sess.derived.signals[0].kind == "decision"
    assert sess.derived.entities[0].name == "matching"

    # Provenance stamps.
    assert sess.metadata.enrich_prompt_version == ENRICH_PROMPT_VERSION
    assert sess.metadata.chunk_count == 1
    assert sess.metadata.model_id == "fake-llm"


def test_single_chunk_drops_blank_signals_and_coerces_bad_kinds():
    """Behavior preserved across the C8 rewrite — same defensive coercion."""
    sess = _short_session()
    fake = FakeLLM({
        "summary": "ok",
        "signals": [
            {"kind": "bogus_kind", "text": "coerced to insight"},
            {"kind": "insight", "text": "   "},  # blank → dropped
            {"kind": "decision", "text": "kept"},
        ],
        "entities": [
            {"name": "VoxTerm", "type": "weird"},  # bad type → coerced to concept
            {"name": "", "type": "person"},        # blank name → dropped
        ],
    })
    enrich_session(sess, llm=fake)
    assert {s.kind for s in sess.derived.signals} == {"insight", "decision"}
    assert any(e.name == "VoxTerm" and e.type == "concept" for e in sess.derived.entities)
    assert all(e.name for e in sess.derived.entities)


# ---------------------------------------------------------------------------
# Multi-chunk map-reduce
# ---------------------------------------------------------------------------

def test_multi_chunk_runs_map_then_reduce_with_summary_synth():
    sess = _long_session()
    # The session chunks deterministically given C7's constants; pre-compute
    # the count so we queue the right number of map responses + 1 reduce.
    from transcripts.chunk import chunk_segments
    n_chunks = len(chunk_segments(sess.raw_diarization))
    assert n_chunks >= 2, "fixture should force multi-chunk path"

    # Distinct per-chunk responses: same decision in chunks 0 and last → dedup;
    # same entity (different casing) in chunks 0 and 1 → dedup + evidence merge.
    map_responses: list[dict] = []
    for i in range(n_chunks):
        item = {
            "summary": f"chunk {i} talked about it",
            "signals": [{"kind": "action_item", "text": f"do thing {i}", "said_by": [f"speaker_{i % 2}"]}],
            "entities": [{"name": "project-x" if i == 0 else f"thing-{i}",
                          "type": "project", "evidence": f"in chunk {i}"}],
        }
        # Sprinkle a duplicate decision into the first and last chunks.
        if i == 0 or i == n_chunks - 1:
            item["signals"].append({"kind": "decision", "text": "ship matcher first", "said_by": []})
        # Sprinkle a casing-only entity dup into the second chunk.
        if i == 1:
            item["entities"].append({"name": "Project-X", "type": "project", "evidence": "again in 1"})
        map_responses.append(item)
    reduce_response = {"summary": "the team committed to shipping the matcher"}

    fake = FakeLLM(*map_responses, reduce_response)
    enrich_session(sess, llm=fake)

    # 1 call per chunk + 1 reduce summary call.
    assert sess.metadata.chunk_count == n_chunks
    assert len(fake.calls) == n_chunks + 1

    # Reduce summary used (not concatenated partials).
    assert sess.derived.summary == "the team committed to shipping the matcher"

    # Signal dedup: "ship matcher first" appeared in two chunks → kept once.
    signal_texts = [s.text for s in sess.derived.signals]
    assert signal_texts.count("ship matcher first") == 1

    # Entity dedup: "project-x" / "Project-X" → one entity, evidences merged.
    px = [e for e in sess.derived.entities if e.name.lower() == "project-x"]
    assert len(px) == 1
    assert "in chunk 0" in px[0].evidence and "again in 1" in px[0].evidence


def test_reduce_caps_signals_at_max_signals():
    """Even if every chunk yields many signals, the final list is bounded."""
    from transcripts.config import MAX_SIGNALS

    partials = [
        {"summary": "s", "signals": [
            {"kind": "decision", "text": f"sig-{i}-{j}", "said_by": []}
            for j in range(MAX_SIGNALS)
        ]}
        for i in range(3)
    ]
    fake = FakeLLM({"summary": "merged"})
    derived = _reduce(partials, llm=fake, model=None)
    assert len(derived.signals) == MAX_SIGNALS


def test_reduce_skips_llm_call_when_no_partial_summaries():
    """Edge: every chunk failed to give a summary → no reduce LLM call."""
    fake = FakeLLM()  # no responses queued — if reduce calls LLM, this raises
    partials = [{"summary": "", "signals": [], "entities": []}]
    derived = _reduce(partials, llm=fake, model=None)
    assert derived.summary is None
    assert fake.calls == []


# ---------------------------------------------------------------------------
# Dedup helpers
# ---------------------------------------------------------------------------

def test_dedup_entities_merges_evidence_strings():
    out = _dedup_entities([
        {"name": "Shape Rotator", "type": "project", "evidence": "chunk 0 evidence"},
        {"name": "shape rotator", "type": "project", "evidence": "chunk 1 evidence"},
        {"name": "  Shape  Rotator  ", "type": "project", "evidence": "chunk 1 evidence"},  # dup of either
    ])
    assert len(out) == 1
    assert "chunk 0 evidence" in out[0].evidence
    assert "chunk 1 evidence" in out[0].evidence


def test_dedup_signals_keeps_first_occurrence():
    out = _dedup_signals([
        {"kind": "decision", "text": "Ship the matcher", "said_by": ["s1"]},
        {"kind": "decision", "text": "ship the matcher", "said_by": []},
        {"kind": "insight", "text": "different signal"},
    ])
    assert [s.text for s in out] == ["Ship the matcher", "different signal"]


# ---------------------------------------------------------------------------
# enrich_pending — backfill pass + provider-error resilience
# ---------------------------------------------------------------------------

def test_enrich_pending_only_touches_pending(tmp_db):
    """Already-enriched current-version sessions are left alone."""
    fresh = _short_session()
    fresh.session_id = "fresh"
    store.save_session(fresh)  # pending: derived empty

    done = _short_session()
    done.session_id = "done"
    done.derived = Derived(summary="already there", signals=[], entities=[])
    done.metadata.enrich_prompt_version = ENRICH_PROMPT_VERSION
    store.save_session(done)

    fake = FakeLLM({"summary": "freshly enriched", "signals": [], "entities": []})
    report = enrich_pending(llm=fake)

    assert report.enriched == 1
    assert report.skipped_unavailable == 0
    # Only one fake call → "done" was correctly skipped.
    assert len(fake.calls) == 1
    assert store.load_session("fresh").derived.summary == "freshly enriched"
    assert store.load_session("done").derived.summary == "already there"


def test_enrich_pending_survives_llm_unavailable(tmp_db):
    """A credit-wall on one session must not crash the rest of the batch."""
    s1 = _short_session(); s1.session_id = "s1"; store.save_session(s1)
    s2 = _short_session(); s2.session_id = "s2"; store.save_session(s2)
    s3 = _short_session(); s3.session_id = "s3"; store.save_session(s3)

    # First call raises (the credit-wall), the other two succeed. Iteration
    # order from list_pending is not contractually ordered by session_id, so
    # we assert on counts, not which specific id failed.
    fake = FakeLLM(
        ConnectionError("daemon down"),
        {"summary": "ok-a", "signals": [], "entities": []},
        {"summary": "ok-b", "signals": [], "entities": []},
    )
    report = enrich_pending(llm=fake)

    assert report.enriched == 2
    assert report.skipped_unavailable == 1
    # Exactly one of the three is still pending; the other two carry a summary.
    after = {sid: store.load_session(sid).derived.summary for sid in ("s1", "s2", "s3")}
    summaries = sorted([v for v in after.values() if v is not None])
    assert summaries == ["ok-a", "ok-b"]
    assert sum(1 for v in after.values() if v is None) == 1


def test_enrich_pending_recognizes_stale_prompt_version(tmp_db):
    s = _short_session(); s.session_id = "old"
    s.derived = Derived(summary="old", signals=[], entities=[])
    s.metadata.enrich_prompt_version = "v0"  # older than current
    store.save_session(s)

    fake = FakeLLM({"summary": "new", "signals": [], "entities": []})
    report = enrich_pending(llm=fake)

    assert report.enriched == 1
    assert store.load_session("old").derived.summary == "new"
    assert store.load_session("old").metadata.enrich_prompt_version == ENRICH_PROMPT_VERSION


# ---------------------------------------------------------------------------
# transcript_text — still rendered with the verbatim labels
# ---------------------------------------------------------------------------

def test_transcript_text_uses_verbatim_speaker_labels():
    s = Session(
        session_id="x",
        raw_diarization=[
            RawSegment(speaker="Alex (flashbots?)", text="hi", start=0.0),
            RawSegment(speaker="Speaker 1", text="hello", start=1.0),
        ],
        metadata=SessionMetadata(date="2026-05-20", source="otter"),
    )
    txt = transcript_text(s)
    assert "[Alex (flashbots?)] hi" in txt
    assert "[Speaker 1] hello" in txt


# ---------------------------------------------------------------------------
# Optional: real local qwen end-to-end (auto-skipped without Ollama)
# ---------------------------------------------------------------------------

@pytest.mark.requires_ollama
def test_enrich_single_chunk_against_local_qwen():
    """Real qwen2.5-conclave call on a tiny session. Shape-only assertions."""
    import os
    os.environ["CONCLAVE_LLM_BACKEND"] = "ollama"
    import importlib
    import config as _cfg
    importlib.reload(_cfg)

    sess = _short_session()
    enrich_session(sess)

    # Wiring works end-to-end: derived populated, provenance stamped.
    assert isinstance(sess.derived.summary, str) and sess.derived.summary.strip()
    assert sess.derived.signals is not None  # may be [] if model finds nothing
    assert sess.derived.entities is not None
    assert sess.metadata.enrich_prompt_version == ENRICH_PROMPT_VERSION
    assert sess.metadata.chunk_count == 1
    assert sess.metadata.model_id  # some non-empty backend id
