"""Phase 3.5b C15 — entity resolution threshold bands (fake embed + LLM)."""
from __future__ import annotations

import json
import math

import pytest

from transcripts.entity_resolution import (
    AUTO_MERGE_THRESHOLD,
    TIEBREAK_THRESHOLD,
    ResolutionDecision,
    cosine,
    resolve_entity,
)


def unit(angle_deg: float) -> list[float]:
    """2-d unit vector at angle — lets tests dial exact cosines."""
    rad = math.radians(angle_deg)
    return [math.cos(rad), math.sin(rad)]


def embed_for(mapping):
    def _fn(texts):
        return [mapping[t] for t in texts]
    return _fn


class SameLLM:
    def __init__(self, same: bool):
        self.same = same
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)

        class R:
            content = json.dumps({"same": self.same})
        R.content = json.dumps({"same": self.same})
        return R()


EXISTING = [{"id": "e1", "type": "project", "canonical_name": "Elocute",
             "embedding": unit(0)}]


def test_auto_merge_above_090():
    fn = embed_for({"elocute app": unit(10)})  # cos(10°) ≈ 0.985
    d = resolve_entity(
        {"type": "project", "canonical_name": "elocute app"},
        EXISTING, embed_fn=fn,
    )
    assert d.action == "merge" and d.target_id == "e1"
    assert d.similarity > AUTO_MERGE_THRESHOLD
    assert not d.llm_tiebreak_used


def test_tiebreak_band_llm_yes():
    fn = embed_for({"Elocute v2": unit(35)})  # cos(35°) ≈ 0.819
    llm = SameLLM(True)
    d = resolve_entity(
        {"type": "project", "canonical_name": "Elocute v2"},
        EXISTING, embed_fn=fn, llm=llm,
    )
    assert d.action == "merge" and d.llm_tiebreak_used
    assert TIEBREAK_THRESHOLD <= d.similarity <= AUTO_MERGE_THRESHOLD
    assert len(llm.calls) == 1


def test_tiebreak_band_llm_no():
    fn = embed_for({"Eloquent ORM": unit(35)})
    d = resolve_entity(
        {"type": "project", "canonical_name": "Eloquent ORM"},
        EXISTING, embed_fn=fn, llm=SameLLM(False),
    )
    assert d.action == "new" and d.llm_tiebreak_used


def test_below_band_new_no_llm():
    fn = embed_for({"Wikigen": unit(60)})  # cos(60°) = 0.5
    llm = SameLLM(True)
    d = resolve_entity(
        {"type": "project", "canonical_name": "Wikigen"},
        EXISTING, embed_fn=fn, llm=llm,
    )
    assert d.action == "new" and not d.llm_tiebreak_used
    assert llm.calls == []  # no spurious tiebreak calls below the band


def test_multi_candidate_picks_best():
    pool = [
        {"id": "far", "type": "topic", "canonical_name": "A", "embedding": unit(80)},
        {"id": "near", "type": "topic", "canonical_name": "B", "embedding": unit(5)},
    ]
    fn = embed_for({"thing": unit(0)})
    d = resolve_entity({"type": "topic", "canonical_name": "thing"}, pool, embed_fn=fn)
    assert d.action == "merge" and d.target_id == "near"


def test_person_exact_match_no_embedding():
    pool = [{"id": "p1", "type": "person", "canonical_name": "Andrew Miller"}]
    d = resolve_entity(
        {"type": "person", "canonical_name": "andrew miller"}, pool,
        embed_fn=lambda texts: pytest.fail("person path must not embed"),
    )
    assert d.action == "merge" and d.target_id == "p1" and d.similarity == 1.0


def test_person_no_match_is_new():
    pool = [{"id": "p1", "type": "person", "canonical_name": "Andrew Miller"}]
    d = resolve_entity({"type": "person", "canonical_name": "Andrew"}, pool)
    assert d.action == "new"  # partial names do NOT merge people (v1.5)


def test_empty_pool_and_type_mismatch():
    d = resolve_entity({"type": "tool", "canonical_name": "X"}, [])
    assert d.action == "new"
    d = resolve_entity(
        {"type": "tool", "canonical_name": "X"},
        [{"id": "e", "type": "project", "canonical_name": "X", "embedding": unit(0)}],
    )
    assert d.action == "new"  # same name, different type — never merged


def test_tiebreak_failure_keeps_separate():
    class Broken:
        def invoke(self, messages):
            raise ConnectionError("down")
    fn = embed_for({"Elocute v2": unit(35)})
    d = resolve_entity(
        {"type": "project", "canonical_name": "Elocute v2"},
        EXISTING, embed_fn=fn, llm=Broken(),
    )
    assert d.action == "new"  # conservative on failure


def test_embed_failure_defaults_new():
    def broken(texts):
        raise RuntimeError("ollama down")
    d = resolve_entity(
        {"type": "project", "canonical_name": "X"}, EXISTING, embed_fn=broken,
    )
    assert d.action == "new"


def test_cosine_guards():
    assert cosine([0, 0], [1, 0]) == 0.0
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)
