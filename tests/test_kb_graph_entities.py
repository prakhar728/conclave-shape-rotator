"""Commit 3 (OI-7 fix) — `category_of`, definition/role storage, category-pooling.

Uses the shared per-process test DB (tests/conftest.py) — entities persist across
tests, so assertions key on the returned ids and use unique names.
"""
from __future__ import annotations

import pytest

from storage import kb_graph
from storage.sqlite import _get_conn
from transcripts.embed import EMBED_MODEL_ID


@pytest.fixture(autouse=True)
def _clean_unique_entities():
    """Shared per-process DB → remove the entities this module creates so other
    modules (e.g. the empty-table assertion in test_kb_extract_pipeline) stay
    isolated. All names here carry the 'Unique' marker."""
    yield
    conn = _get_conn()
    conn.execute(
        "DELETE FROM embeddings WHERE source_kind='entity' AND source_id IN "
        "(SELECT id FROM entities WHERE canonical_name LIKE '%Unique%')"
    )
    conn.execute("DELETE FROM entities WHERE canonical_name LIKE '%Unique%'")


def test_category_of_mapping():
    assert kb_graph.category_of("person") == "person"
    assert kb_graph.category_of("company") == "affiliation"
    for t in ("tool", "project", "topic"):
        assert kb_graph.category_of(t) == "tech"


def test_insert_entity_round_trips_definition_and_role():
    eid = kb_graph.insert_entity(
        "person", "Zeta Unique Person", ["Zeta"],
        definition="a researcher who studies TEEs", role="researcher",
    )
    mine = next(e for e in kb_graph.entities_for_er("person", model_id=EMBED_MODEL_ID)
                if e["id"] == eid)
    assert mine["definition"] == "a researcher who studies TEEs"
    assert (mine.get("props") or {}).get("role") == "researcher"


def test_insert_entity_without_fields_is_clean():
    eid = kb_graph.insert_entity("topic", "Plain Topic Unique", ["plain"])
    mine = next(e for e in kb_graph.entities_for_er("topic", model_id=EMBED_MODEL_ID)
                if e["id"] == eid)
    assert mine["definition"] is None
    props = mine.get("props") or {}
    assert "definition" not in props and "role" not in props   # not persisted when empty


def test_category_pooling_unifies_tech_types():
    tool = kb_graph.insert_entity("tool", "QzxTool Unique", ["QzxTool"], definition="d1")
    proj = kb_graph.insert_entity("project", "QzxProj Unique", ["QzxProj"], definition="d2")
    # a tool candidate is pooled against the whole tech category (tool+project+topic)
    tech_ids = {e["id"] for e in kb_graph.entities_for_er("tool", model_id=EMBED_MODEL_ID)}
    assert tool in tech_ids and proj in tech_ids
    # the affiliation pool must NOT contain tech entities
    aff_ids = {e["id"] for e in kb_graph.entities_for_er("company", model_id=EMBED_MODEL_ID)}
    assert tool not in aff_ids and proj not in aff_ids
