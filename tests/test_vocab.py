"""Part 1 increment 1c — per-user vocab seam (GT-1/GT-6/GT-7/CD-21 mechanics).

Pure store-level. Each test uses a unique user_id for isolation.
"""
from __future__ import annotations

from transcripts import vocab


def test_put_get_roundtrip():  # GT-1 (seam)
    vocab.put("u_put", "DStack protocol", is_entity=True, type="project", provenance="user")
    e = vocab.get("u_put", "DStack protocol")
    assert e is not None
    assert e.is_entity is True
    assert e.type == "project"
    assert e.provenance == "user"


def test_normalized_lookup():  # CD-21
    vocab.put("u_norm", "DStack Protocol", type="project")
    # different case + whitespace hits the same key
    assert vocab.get("u_norm", "  dstack   protocol ") is not None
    assert vocab.get("u_norm", "dstack protocol").type == "project"


def test_per_user_keyed():  # GT-6
    vocab.put("uA", "dstack", type="project")
    vocab.put("uB", "dstack", type="company")
    assert vocab.get("uA", "dstack").type == "project"
    assert vocab.get("uB", "dstack").type == "company"


def test_retag_updates_single_entry():  # GT-7
    vocab.put("u_retag", "phala", type="project")
    vocab.put("u_retag", "phala", type="company")  # retag same surface
    e = vocab.get("u_retag", "phala")
    assert e.type == "company"
    assert len(vocab.list_for_user("u_retag")) == 1  # no duplicate row


def test_get_miss_returns_none():
    assert vocab.get("u_nobody", "nothing here") is None


def test_new_vocab_non_entity_provenance():  # GT-2-ish
    vocab.put("u_new", "newcoinedterm", is_entity=False, provenance="correction")
    e = vocab.get("u_new", "newcoinedterm")
    assert e.is_entity is False
    assert e.provenance == "correction"


def test_list_for_user_is_scoped():  # GT-6 / IS-1 (seam-level)
    vocab.put("u_list1", "alpha", type="project")
    vocab.put("u_list1", "beta", type="tool")
    vocab.put("u_list2", "gamma", type="company")
    surfaces = {e.surface_norm for e in vocab.list_for_user("u_list1")}
    assert surfaces == {"alpha", "beta"}
    assert vocab.get("u_list2", "alpha") is None
