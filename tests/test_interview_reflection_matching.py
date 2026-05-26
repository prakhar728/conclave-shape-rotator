"""
S8 tests — cohort matching engine (matching.run_matching).

Embeddings are forced to the deterministic hash fallback (monkeypatch
_get_model → None) so the tests are offline and stable. Profiles are seeded
directly into a tmp ledger via append_digest. Verifies the three intro types,
that help intros carry both evidence quotes + the driving tags, and that
genuinely disjoint profiles produce no intros.
"""
from __future__ import annotations

import pytest

from skills.interview_reflection import matching
from skills.interview_reflection.aggregate import append_digest


@pytest.fixture(autouse=True)
def force_fallback_embeddings(monkeypatch):
    monkeypatch.setattr(matching, "_get_model", lambda: None)
    yield


def _digest(slug, profile):
    return {"submission_id": f"{slug}-s1", "interviewee_slug": slug,
            "collaboration_profile": profile}


def _seed(tmp_path, slug, profile):
    append_digest(slug, _digest(slug, profile), root=tmp_path)


def _item(text, tags, quote, credibility=None):
    d = {"text": text, "tags": tags, "quote": quote}
    if credibility:
        d["credibility"] = credibility
    return d


# --- help ---

def test_help_intro_with_both_quotes(tmp_path):
    _seed(tmp_path, "alice", {
        "building": "a defi app", "building_tags": ["defi"], "stage": "prototype",
        "needs": [_item("token economics", ["tokenomics"], "I'm stuck on our token economics")],
        "offers": [], "interests": [],
    })
    _seed(tmp_path, "bob", {
        "building": "a defi protocol", "building_tags": ["defi"], "stage": "prototype",
        "needs": [],
        "offers": [_item("mechanism design", ["tokenomics"],
                         "I spent a year on mechanism design", "demonstrated")],
        "interests": [],
    })

    out = matching.run_matching(root=tmp_path)
    help_intros = [i for i in out["intros"] if i["type"] == "help"]
    a2b = [i for i in help_intros if i["from"] == "alice" and i["to"] == "bob"]
    assert a2b, "expected an alice→bob help intro"
    intro = a2b[0]
    assert intro["tags"] == ["tokenomics"]
    assert intro["quote_from"] == "I'm stuck on our token economics"
    assert intro["quote_to"] == "I spent a year on mechanism design"
    assert intro["score"] > 0


def test_help_is_directional(tmp_path):
    """bob offers, alice needs → help only alice→bob, not bob→alice."""
    _seed(tmp_path, "alice", {
        "building_tags": ["defi"], "stage": "prototype",
        "needs": [_item("tokenomics", ["tokenomics"], "stuck on tokenomics")],
        "offers": [], "interests": [],
    })
    _seed(tmp_path, "bob", {
        "building_tags": ["defi"], "stage": "prototype", "needs": [],
        "offers": [_item("mechanism design", ["tokenomics"], "did mechanism design")],
        "interests": [],
    })
    out = matching.run_matching(root=tmp_path)
    help_dirs = {(i["from"], i["to"]) for i in out["intros"] if i["type"] == "help"}
    assert ("alice", "bob") in help_dirs
    assert ("bob", "alice") not in help_dirs


# --- peer ---

def test_peer_intro_for_same_domain_same_stage(tmp_path):
    for slug in ("carol", "dave"):
        _seed(tmp_path, slug, {
            "building": f"{slug} consumer payments app", "building_tags": ["payments"],
            "stage": "early-traction", "needs": [], "offers": [], "interests": [],
        })
    out = matching.run_matching(root=tmp_path)
    peers = [i for i in out["intros"] if i["type"] == "peer"]
    assert any({i["from"], i["to"]} == {"carol", "dave"} for i in peers)
    assert peers[0]["tags"] == ["payments"]


def test_no_peer_when_stage_far_apart(tmp_path):
    _seed(tmp_path, "carol", {"building_tags": ["payments"], "stage": "idea",
                              "needs": [], "offers": [], "interests": []})
    _seed(tmp_path, "dave", {"building_tags": ["payments"], "stage": "scaling",
                             "needs": [], "offers": [], "interests": []})
    out = matching.run_matching(root=tmp_path)
    assert not [i for i in out["intros"] if i["type"] == "peer"]


# --- cross-pollinate ---

def test_cross_pollinate_for_adjacent_domains(tmp_path, monkeypatch):
    # payments & fintech are in the same DOMAIN_GROUP (adjacent, not identical).
    # Pin cosine into the mid-band so the cross gate fires deterministically.
    monkeypatch.setattr(matching, "_cosine", lambda *_a, **_k: 0.5)
    _seed(tmp_path, "erin", {"building": "payments rails", "building_tags": ["payments"],
                             "stage": "prototype", "needs": [], "offers": [], "interests": []})
    _seed(tmp_path, "finn", {"building": "neobank ledger", "building_tags": ["fintech"],
                             "stage": "prototype", "needs": [], "offers": [], "interests": []})
    out = matching.run_matching(root=tmp_path)
    cross = [i for i in out["intros"] if i["type"] == "cross-pollinate"]
    assert cross, "expected a cross-pollinate intro for adjacent domains"
    assert {cross[0]["from"], cross[0]["to"]} == {"erin", "finn"}
    assert not [i for i in out["intros"] if i["type"] == "peer"]   # different tags → not peers


# --- no signal ---

def test_disjoint_profiles_produce_no_intros(tmp_path):
    _seed(tmp_path, "gina", {"building": "a gaming studio", "building_tags": ["gaming"],
                             "stage": "idea",
                             "needs": [_item("art", ["design-ux"], "need a pixel artist")],
                             "offers": [], "interests": []})
    _seed(tmp_path, "hugo", {"building": "a climate sensor", "building_tags": ["climate"],
                             "stage": "scaling", "needs": [],
                             "offers": [_item("hardware", ["hardware"], "built sensor arrays")],
                             "interests": []})
    out = matching.run_matching(root=tmp_path)
    assert out["intros"] == []
    assert {n["slug"] for n in out["graph"]["nodes"]} == {"gina", "hugo"}


# --- graph shape ---

def test_graph_nodes_and_edges(tmp_path):
    _seed(tmp_path, "alice", {
        "building_tags": ["defi"], "stage": "prototype",
        "needs": [_item("tokenomics", ["tokenomics"], "stuck on tokenomics")],
        "offers": [], "interests": []})
    _seed(tmp_path, "bob", {
        "building_tags": ["defi"], "stage": "prototype", "needs": [],
        "offers": [_item("mechanism design", ["tokenomics"], "did mechanism design")],
        "interests": []})
    out = matching.run_matching(root=tmp_path)
    assert {n["slug"] for n in out["graph"]["nodes"]} == {"alice", "bob"}
    assert len(out["graph"]["edges"]) == len(out["intros"])
    assert all({"from", "to", "type", "score"} == set(e) for e in out["graph"]["edges"])


def test_top_k_limits_intros(tmp_path):
    for slug in ("carol", "dave", "erin"):
        _seed(tmp_path, slug, {"building": f"{slug} payments", "building_tags": ["payments"],
                               "stage": "early-traction", "needs": [], "offers": [], "interests": []})
    out = matching.run_matching(root=tmp_path, top_k=1)
    assert len(out["intros"]) == 1
