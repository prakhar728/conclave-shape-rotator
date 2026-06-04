"""Phase 3.5c C27 — search-quality regression guard.

Two tiers:

- ``test_fts_ndcg_floor`` — HERMETIC: chunks the 3 fixture transcripts
  into the test DB (pure python + FTS5; no Ollama, no network) and
  asserts FTS-leg NDCG@10 stays above a floor. Catches regressions in
  chunking, FTS indexing, sanitization, or RRF wiring on every run.
  (Measured FTS-only baseline: 0.835 — see EVAL.md C24.)

- ``test_hybrid_ndcg_floor`` — LIVE (needs Ollama embeddings): the
  full hybrid floor of 0.75 pinned in EVAL.md C24/C25.

Both skip cleanly when the fixture transcripts aren't present
(they're gitignored content; yamls alone aren't enough).
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from storage import kb
from storage.sqlite import _get_conn
from storage.vec import vec_available
from transcripts.kb_chunk import chunk_transcript
from transcripts.sources import read_file

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "transcripts"
SLUGS = ["elocute", "dstack-intro-salon", "project-intros-agents-day3"]

FTS_FLOOR = 0.70     # FTS-only baseline 0.835 minus generous drift slack
HYBRID_FLOOR = 0.75  # EVAL.md C24/C25 pinned floor (baseline 0.814)


def _fixtures_present() -> bool:
    for slug in SLUGS:
        gold = yaml.safe_load(open(FIXTURE_DIR / f"{slug}.expected.yaml"))
        if not (FIXTURE_DIR / gold["transcript"]).exists():
            return False
    return True


pytestmark = pytest.mark.skipif(
    not _fixtures_present(),
    reason="fixture transcripts not present (gitignored content)",
)


def _ndcg(rels: list[int], n_relevant: int, k: int = 10) -> float:
    dcg = sum(r / math.log2(i + 2) for i, r in enumerate(rels[:k]))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(n_relevant, k)))
    return dcg / ideal if ideal else 0.0


@pytest.fixture(scope="module")
def indexed_fixtures():
    """Chunk + FTS-index the three fixtures into the test DB.

    Saves a parent Session row per fixture first (chunks.session_id is
    a foreign key into transcript_sessions).
    """
    from transcripts import store
    from transcripts.models import Derived, RawSegment, Session, SessionMetadata

    session_ids = {}
    for slug in SLUGS:
        gold = yaml.safe_load(open(FIXTURE_DIR / f"{slug}.expected.yaml"))
        ni = read_file(FIXTURE_DIR / gold["transcript"])
        sid = f"reg-{slug}"
        store.save_session(Session(
            session_id=sid,
            raw_diarization=[
                RawSegment(speaker=s["speaker"], text=s["text"],
                           start=s.get("start"), end=s.get("end"))
                for s in ni.segments
            ],
            metadata=SessionMetadata(date="2026-06-04", source="reg", tags=[]),
            derived=Derived(),
        ))
        chunks = chunk_transcript(ni.segments)
        kb.save_chunks(sid, chunks)
        session_ids[slug] = (sid, gold, {
            kb.chunk_id(sid, c.chunk_index): set(c.turn_ids) for c in chunks
        })
    yield session_ids
    conn = _get_conn()
    for sid, _, _ in session_ids.values():
        kb.delete_chunks_for_session(sid)
        conn.execute("DELETE FROM transcript_sessions WHERE session_id = ?", (sid,))


def _score(slugs_data, retrieve) -> float:
    scores = []
    for slug, (sid, gold, turns_by_chunk) in slugs_data.items():
        for q in gold.get("queries") or []:
            rel_turns = set(q["relevant_turn_ids"])
            relevant = {
                cid for cid, turns in turns_by_chunk.items() if turns & rel_turns
            }
            if not relevant:
                continue
            ranked = retrieve(q["q"], sid)
            rels = [1 if cid in relevant else 0 for cid in ranked]
            scores.append(_ndcg(rels, len(relevant)))
    assert scores, "no scorable queries — eval set broken?"
    return sum(scores) / len(scores)


def test_fts_ndcg_floor(indexed_fixtures):
    def retrieve(query: str, sid: str) -> list[str]:
        hits = kb.fts_search_chunks(query, limit=10, session_ids=[sid])
        return [h["chunk_id"] for h in hits]

    mean = _score(indexed_fixtures, retrieve)
    assert mean >= FTS_FLOOR, (
        f"FTS NDCG@10 regressed: {mean:.3f} < floor {FTS_FLOOR} "
        f"(baseline 0.835 — see transcripts/EVAL.md C24)"
    )


@pytest.mark.live
def test_hybrid_ndcg_floor(indexed_fixtures):
    if not vec_available(_get_conn()):
        pytest.skip("sqlite-vec not loaded")
    from infra.rrf import rrf_fuse
    from transcripts.embed import embed_texts

    # embed the regression chunks so the vec leg has an index
    for sid, _, turns_by_chunk in indexed_fixtures.values():
        rows = kb.query_chunks_for_session(sid)
        vecs = embed_texts([r["text"] for r in rows], kind="document")
        kb.save_chunk_embeddings(
            sid, {r["id"]: v for r, v in zip(rows, vecs)},
            model_id="nomic-embed-text:v1.5",
        )

    def retrieve(query: str, sid: str) -> list[str]:
        fts = [h["chunk_id"] for h in
               kb.fts_search_chunks(query, limit=50, session_ids=[sid])]
        qvec = embed_texts([query], kind="query")[0]
        vec = [h["chunk_id"] for h in
               kb.vec_search_chunks(qvec, k=50, session_ids=[sid])]
        return [cid for cid, _ in rrf_fuse([fts, vec])][:10]

    mean = _score(indexed_fixtures, retrieve)
    assert mean >= HYBRID_FLOOR, (
        f"hybrid NDCG@10 regressed: {mean:.3f} < floor {HYBRID_FLOOR} "
        f"(baseline 0.814 — see transcripts/EVAL.md C24)"
    )
