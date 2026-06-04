"""Phase 3.5a C8 — embedding module tests (fake transport; one live-optional)."""
from __future__ import annotations

import math

import pytest

from transcripts.embed import (
    BATCH_SIZE,
    DOC_PREFIX,
    QUERY_PREFIX,
    EmbeddingUnavailable,
    deserialize_f32,
    embed_texts,
    serialize_f32,
    truncate_matryoshka,
)


def fake_transport(calls):
    def _t(model, inputs):
        calls.append((model, list(inputs)))
        return [[0.1] * 768 for _ in inputs]
    return _t


def test_document_prefix_applied():
    calls = []
    embed_texts(["hello", "world"], transport=fake_transport(calls))
    _, inputs = calls[0]
    assert inputs == [DOC_PREFIX + "hello", DOC_PREFIX + "world"]


def test_query_prefix_applied():
    calls = []
    embed_texts(["find me"], kind="query", transport=fake_transport(calls))
    assert calls[0][1] == [QUERY_PREFIX + "find me"]


def test_invalid_kind_rejected():
    with pytest.raises(ValueError):
        embed_texts(["x"], kind="passage")


def test_batching():
    calls = []
    embed_texts(["t"] * (BATCH_SIZE + 3), transport=fake_transport(calls))
    assert len(calls) == 2
    assert len(calls[0][1]) == BATCH_SIZE
    assert len(calls[1][1]) == 3


def test_model_id_passthrough():
    calls = []
    embed_texts(["x"], model_id="custom-embedder", transport=fake_transport(calls))
    assert calls[0][0] == "custom-embedder"


def test_truncate_matryoshka_renormalizes():
    vec = [1.0] * 768
    out = truncate_matryoshka(vec, 256)
    assert len(out) == 256
    norm = math.sqrt(sum(x * x for x in out))
    assert norm == pytest.approx(1.0)


def test_truncate_zero_vector_safe():
    assert truncate_matryoshka([0.0] * 768, 4) == [0.0] * 4


def test_serialize_round_trip():
    vec = [0.25, -1.5, 3.0]
    assert deserialize_f32(serialize_f32(vec)) == pytest.approx(vec)


@pytest.mark.live
def test_live_ollama_round_trip():
    """Requires local Ollama + nomic-embed-text:v1.5 (make ollama-check)."""
    vecs = embed_texts(["the quick brown fox"])
    assert len(vecs) == 1
    assert len(vecs[0]) == 768
