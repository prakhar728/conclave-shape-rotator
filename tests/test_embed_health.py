"""Embedder-health signals (OI-7 / EVAL.md E1).

The OI-7 over-merge bug was *not* a threshold or LLM problem — it was that the
embedder (`nomic-embed-text:v1.5` via Ollama) returns a **near-constant vector
for ultra-short inputs**, so bare entity names ("DStack", "ChatGPT", "Benchling")
collapse onto one point with cosine ~1.0 between them. `resolve_entity` then
auto-merged them (cos > 0.90) without ever consulting the LLM.

No prior eval could see this: the resolution unit tests inject *synthetic*
fixed-angle vectors, so they assume the embedder is meaningful. These tests call
the **real** embedder and would have caught the collapse immediately.

- `test_short_names_collapse_*` documents the known limitation (xfail): short
  distinct names should embed distinctly, but today they don't. The resolver fix
  (lexical gate) removes our *dependence* on this rather than fixing the embedder,
  so this stays xfail until the embedding path itself is changed.
- `test_long_text_embeds_distinctly` is the positive control: long text embeds
  fine, proving the collapse is short-input-specific and the retrieval/search
  layer (which embeds chunks, not names) is unaffected.

All auto-skipped when Ollama / the model isn't available (see tests/conftest.py).
"""
from __future__ import annotations

import pytest

from transcripts.embed import embed_texts
from transcripts.entity_resolution import cosine

#: Clearly-unrelated short entity-style names. A healthy embedder keeps these
#: well apart; the degenerate one collapses them onto a single vector.
SHORT_NAMES = ["DStack", "ChatGPT", "Benchling", "Ethereum", "Jupyter", "Hermes"]

#: A merge-decision-relevant ceiling: unrelated names must not look ~identical.
COLLAPSE_COSINE = 0.97


def _max_offdiag_cosine(vecs: list[list[float]]) -> float:
    m = 0.0
    for i in range(len(vecs)):
        for j in range(i + 1, len(vecs)):
            m = max(m, cosine(vecs[i], vecs[j]))
    return m


@pytest.mark.requires_ollama
@pytest.mark.xfail(
    reason="OI-7/E1: nomic-embed collapses ultra-short inputs to a near-constant "
    "vector; the resolver fix removes dependence on name-embedding cosine rather "
    "than fixing the embedder. Flips to xpass only if the embedding path changes.",
    strict=False,
)
def test_short_names_embed_distinctly():
    """Distinct short names SHOULD embed distinctly (currently they don't)."""
    vecs = embed_texts(SHORT_NAMES, kind="document")
    worst = _max_offdiag_cosine(vecs)
    assert worst < COLLAPSE_COSINE, (
        f"short names collapse: max pairwise cosine {worst:.4f} >= {COLLAPSE_COSINE} "
        "— the embedder returns ~one vector for ultra-short inputs (OI-7)."
    )


@pytest.mark.requires_ollama
def test_short_name_collapse_is_present_today():
    """Lock the *current* degenerate behaviour so a silent change is noticed.

    This is the mirror of the xfail above: it asserts the collapse EXISTS now, so
    if the embedder is ever fixed (or swapped) this test fails loudly and we
    revisit the resolver's reliance assumptions. Kept narrow to avoid flakiness.
    """
    a, b = embed_texts(["DStack", "Benchling"], kind="document")
    assert cosine(a, b) >= COLLAPSE_COSINE, (
        "short-name collapse no longer reproduces — re-evaluate OI-7 assumptions "
        "and the resolver lexical-gate rationale."
    )


@pytest.mark.requires_ollama
def test_long_text_embeds_distinctly():
    """Positive control: long text embeds fine → retrieval/search is unaffected."""
    a, b = embed_texts(
        [
            "the quarterly board reviewed the marine biology research budget",
            "a python script parsed the kubernetes deployment manifest at dawn",
        ],
        kind="document",
    )
    assert cosine(a, b) < 0.90, "long-text embeddings unexpectedly collapsed"


@pytest.mark.requires_ollama
def test_identical_text_is_identical():
    """Sanity: same string → cosine 1.0 (embedder is deterministic)."""
    a, b = embed_texts(["Conclave", "Conclave"], kind="document")
    assert cosine(a, b) == pytest.approx(1.0, abs=1e-6)
