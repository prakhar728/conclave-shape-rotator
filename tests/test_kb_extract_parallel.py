"""Parallel per-chunk extraction must be OUTPUT-EQUIVALENT to sequential.

`_extract_all_chunks` runs the per-chunk LLM calls in a bounded thread pool. The
only guarantee that matters: the result is identical (content AND order) to the
old sequential loop — only wall-clock changes. A tiny per-call sleep + reversed
finish order would expose any ordering race; `ThreadPoolExecutor.map` preserves
input order, so it doesn't. No DB, no network (stubbed extractor).
"""
from __future__ import annotations

import time

from transcripts import kb_extract
from transcripts.extract import ExtractionResult


def _stub_extract(text, header="", *, turn_count=None, llm=None, model=None):
    # Per-chunk deterministic output keyed by the chunk index encoded in the text.
    # The sleep (longer for earlier chunks) makes a naive parallel collection
    # finish out of order — the test then proves order is still preserved.
    idx = int(text.split("#")[1])
    time.sleep(0.02 * (5 - (idx % 5)))
    return ExtractionResult(
        entities=[{
            "type": "tool", "canonical_name": f"E{idx}", "definition": f"def {idx}",
            "role": None, "raw_mentions": [f"E{idx}"], "turn_ids": [idx],
        }],
        obligations=[{
            "type": "action", "description": f"do {idx}", "source_quote": "",
            "turn_ids": [idx], "owner_raw_text": None, "due_date_raw": None,
            "status_inferred": "open",
        }],
    )


def _run_at(monkeypatch, concurrency: int, chunks):
    monkeypatch.setattr(kb_extract, "extract_from_chunk", _stub_extract)
    monkeypatch.setattr(kb_extract, "_extract_concurrency", lambda: concurrency)
    return kb_extract._extract_all_chunks(chunks, n_turns=1000)


def test_parallel_extraction_equals_sequential(monkeypatch):
    chunks = [{"text": f"chunk #{i}", "context_header": ""} for i in range(12)]
    seq_e, seq_o = _run_at(monkeypatch, 1, chunks)
    par_e, par_o = _run_at(monkeypatch, 6, chunks)

    assert par_e == seq_e          # identical content AND order
    assert par_o == seq_o
    # order explicitly preserved despite reversed finish times
    assert [e["canonical_name"] for e in par_e] == [f"E{i}" for i in range(12)]
    assert [o["description"] for o in par_o] == [f"do {i}" for i in range(12)]


def test_concurrency_one_is_sequential(monkeypatch):
    chunks = [{"text": f"chunk #{i}", "context_header": ""} for i in range(3)]
    e, o = _run_at(monkeypatch, 1, chunks)
    assert [x["canonical_name"] for x in e] == ["E0", "E1", "E2"]
    assert len(o) == 3


def test_empty_chunks_is_safe(monkeypatch):
    e, o = _run_at(monkeypatch, 6, [])
    assert e == [] and o == []
