"""Entity resolution — OI-7 redesign (Commit 4).

New contract: people = exact casefold; non-person pooled by CATEGORY
(person/tech/affiliation); resolution is (1) lexical gate → deterministic merge,
(2) definition-embedding cosine, (3) LLM tiebreak fed names+definitions. There is
NO bare-cosine auto-merge — the embedding only proposes, the LLM disposes. So a
degenerate high cosine (the OI-7 collapse) can never merge on its own.
"""
from __future__ import annotations

import json
import math

import pytest

from transcripts.entity_resolution import cosine, resolve_entity


def unit(angle_deg: float) -> list[float]:
    rad = math.radians(angle_deg)
    return [math.cos(rad), math.sin(rad)]


def const_embed(angle_deg: float):
    """embed_fn that returns one fixed vector per text (controls candidate cosine
    against pool entities that carry a cached `embedding`)."""
    return lambda texts: [unit(angle_deg) for _ in texts]


class SameLLM:
    def __init__(self, same: bool):
        self.same = same
        self.calls = []

    def invoke(self, messages):
        self.calls.append(messages)

        class R:
            content = json.dumps({"same": self.same})
        return R()


# tech-category pool entity with a cached embedding at angle 0
TOOL_POOL = [{"id": "e1", "type": "tool", "canonical_name": "DStack",
              "definition": "a confidential-computing framework", "embedding": unit(0)}]


# --- lexical gate (deterministic, no embed, no LLM) --------------------------

def test_lexical_exact_merges_without_embed_or_llm():
    llm = SameLLM(True)
    d = resolve_entity(
        {"type": "tool", "canonical_name": "dstack", "definition": "x"},
        TOOL_POOL,
        embed_fn=lambda t: pytest.fail("must not embed on a lexical match"),
        llm=llm,
    )
    assert d.action == "merge" and d.target_id == "e1" and d.similarity == 1.0
    assert not d.llm_tiebreak_used and llm.calls == []


def test_lexical_normalizes_spaces_and_punctuation():
    pool = [{"id": "fb", "type": "tool", "canonical_name": "Flashbots",
             "embedding": unit(0)}]
    d = resolve_entity({"type": "tool", "canonical_name": "Flash-Bots"}, pool,
                       embed_fn=const_embed(90))
    assert d.action == "merge" and d.target_id == "fb"


# --- degenerate-embedding guard: high cosine alone NEVER merges --------------

def test_disjoint_high_cosine_routes_to_llm_and_rejects():
    """The OI-7 case: collapse → cosine 1.0 with an unrelated entity. With no
    auto-merge, it goes to the LLM, which (correctly) says different → new."""
    d = resolve_entity(
        {"type": "tool", "canonical_name": "ChatGPT", "definition": "an LLM chatbot"},
        TOOL_POOL, embed_fn=const_embed(0), llm=SameLLM(False),
    )
    assert d.action == "new" and d.llm_tiebreak_used
    assert d.similarity == pytest.approx(1.0)


def test_high_cosine_llm_yes_merges():
    llm = SameLLM(True)
    d = resolve_entity(
        {"type": "tool", "canonical_name": "DeeStack", "definition": "TEE deploy tool"},
        TOOL_POOL, embed_fn=const_embed(0), llm=llm,
    )
    assert d.action == "merge" and d.target_id == "e1" and d.llm_tiebreak_used
    assert len(llm.calls) == 1


def test_below_threshold_is_new_without_llm():
    llm = SameLLM(True)
    d = resolve_entity(
        {"type": "tool", "canonical_name": "ChatGPT", "definition": "an LLM chatbot"},
        TOOL_POOL, embed_fn=const_embed(60), llm=llm,   # cos 0.5 < 0.75
    )
    assert d.action == "new" and not d.llm_tiebreak_used and llm.calls == []


# --- category pooling --------------------------------------------------------

def test_category_pooling_unifies_tool_and_project():
    pool = [{"id": "p1", "type": "project", "canonical_name": "Qzx",
             "embedding": unit(0)}]
    d = resolve_entity({"type": "tool", "canonical_name": "qzx"}, pool,
                       embed_fn=const_embed(90))
    assert d.action == "merge" and d.target_id == "p1"   # tool↔project share tech pool


def test_cross_category_is_not_pooled():
    pool = [{"id": "per", "type": "person", "canonical_name": "Sam"}]
    d = resolve_entity({"type": "tool", "canonical_name": "Sam",
                        "definition": "a tool"}, pool, embed_fn=const_embed(0))
    assert d.action == "new"     # tech candidate never pools against a person


# --- people: exact match only ------------------------------------------------

def test_person_exact_match_no_embedding():
    pool = [{"id": "pp", "type": "person", "canonical_name": "Andrew Miller"}]
    d = resolve_entity(
        {"type": "person", "canonical_name": "andrew miller"}, pool,
        embed_fn=lambda t: pytest.fail("person path must not embed"),
    )
    assert d.action == "merge" and d.target_id == "pp" and d.similarity == 1.0


def test_person_partial_name_is_new():
    pool = [{"id": "pp", "type": "person", "canonical_name": "Andrew Miller"}]
    d = resolve_entity({"type": "person", "canonical_name": "Andrew"}, pool)
    assert d.action == "new"


# --- failure modes (conservative) -------------------------------------------

def test_empty_pool_is_new():
    assert resolve_entity({"type": "tool", "canonical_name": "X"}, []).action == "new"


def test_embed_failure_defaults_new():
    def broken(texts):
        raise RuntimeError("ollama down")
    d = resolve_entity({"type": "tool", "canonical_name": "ChatGPT",
                        "definition": "chatbot"}, TOOL_POOL, embed_fn=broken)
    assert d.action == "new"


def test_tiebreak_llm_failure_keeps_separate():
    class Broken:
        def invoke(self, messages):
            raise ConnectionError("down")
    d = resolve_entity(
        {"type": "tool", "canonical_name": "ChatGPT", "definition": "chatbot"},
        TOOL_POOL, embed_fn=const_embed(0), llm=Broken(),
    )
    assert d.action == "new"     # conservative on LLM failure


def test_cosine_guards():
    assert cosine([0, 0], [1, 0]) == 0.0
    assert cosine([1, 0], [1, 0]) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# Real-embedder integration (OI-7 / EVAL.md E1). Now a REAL PASS (was xfail in
# Commit 1): lexically-disjoint short names route to the LLM, which rejects them,
# so the bare-name collapse can no longer create a black hole.
# Auto-skipped when Ollama isn't available (tests/conftest.py).
# ---------------------------------------------------------------------------

@pytest.mark.requires_ollama
def test_real_embedder_disjoint_short_names_do_not_merge():
    from transcripts.embed import embed_texts

    def real_embed(texts):
        return embed_texts(texts, kind="document")

    pool = [
        {"id": "t1", "type": "tool", "canonical_name": "Benchling"},
        {"id": "t2", "type": "tool", "canonical_name": "ChatGPT"},
        {"id": "t3", "type": "tool", "canonical_name": "Cowrie"},
    ]
    d = resolve_entity(
        {"type": "tool", "canonical_name": "DStack"},
        pool, embed_fn=real_embed, llm=SameLLM(False),
    )
    assert d.action == "new", (
        f"lexically-disjoint short names merged (target={d.target_id}, "
        f"sim={d.similarity:.4f}) — the OI-7 collapse→auto-merge path is back."
    )
