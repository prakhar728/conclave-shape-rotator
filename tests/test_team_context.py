"""V2 — team_context.py loader + example XML.

Asserts the contract documented in IMPLEMENTATION_PLAN.md v1 §2.2:

- Round-trip: example XML → parses to structured fields → ``to_prompt_fragment``
  returns the raw XML body verbatim.
- Missing file → ``load()`` returns ``None`` + warning log; never raises.
- Malformed XML → ``load()`` returns ``None`` + warning log; never raises.
- ``team_context_version`` (SHA-256 prefix, 8 chars) is deterministic and
  changes when the XML body changes.
- Env-var override (``CONCLAVE_TEAM_CONTEXT``) is honored.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from transcripts import team_context as tc
from transcripts.team_context import ENV_VAR, TeamContext, load


# ---------------------------------------------------------------------------
# Round-trip on the shipped example
# ---------------------------------------------------------------------------

def test_example_xml_loads_and_parses():
    """The shipped example file must parse cleanly so the demo works
    out of the box for fresh checkouts.

    The v1 XML is compiled from ``external/shape-rotator-os/cohort-data``
    (26 cohort teams as ``<known_projects>``), so the assertions here
    check for cohort-data-sourced projects rather than the curated set
    in the original hand-written XML.
    """
    ctx = load()  # default path → transcripts/team_context.example.xml
    assert ctx is not None
    assert ctx.team_name == "Shape Rotator Cohort"
    assert ctx.domain == "confidential AI infrastructure"
    # Cohort-data-sourced projects present (26 teams).
    project_names = {p["name"] for p in ctx.known_projects}
    assert "Conclave" in project_names
    assert "Elocute" in project_names           # Albiona's project
    assert "Crossroads" in project_names         # Chloe's project
    assert len(project_names) >= 20              # we expect ~26 teams
    # Curated technologies still present.
    tech_names = {t["name"] for t in ctx.known_technologies}
    assert "TDX" in tech_names
    assert "TEE" in tech_names
    assert "Phala" in tech_names                 # Phala is a tech, not a team
    # Topics list populated (curated + cluster labels).
    assert "attestation" in ctx.known_topics
    # Style guide covers every signal kind in _VALID_SIGNAL_KINDS.
    from transcripts.enrich import _VALID_SIGNAL_KINDS
    assert set(ctx.style_guide) == _VALID_SIGNAL_KINDS
    # Extraction examples present — at least one of each major kind.
    example_kinds: set[str] = set()
    for ex in ctx.extraction_examples:
        # We just check the expected JSON literal mentions the kind.
        for kind in _VALID_SIGNAL_KINDS:
            if f'"kind": "{kind}"' in ex["expected"]:
                example_kinds.add(kind)
    # The example file ships with decision, action_item, open_question covered.
    assert {"action_item", "open_question", "insight"}.issubset(example_kinds)
    # Open-world note carries the non-exhaustive language.
    assert "NON-EXHAUSTIVE" in ctx.open_world_note


def test_to_prompt_fragment_returns_raw_xml_verbatim():
    """Adopters editing the XML can predict what the model sees — same text."""
    ctx = load()
    assert ctx is not None
    fragment = ctx.to_prompt_fragment()
    # Verbatim — same bytes the adopter wrote.
    assert fragment == ctx.raw_xml
    # And the raw XML opens with the root element.
    assert "<team_context>" in fragment
    assert "</team_context>" in fragment


# ---------------------------------------------------------------------------
# Version (SHA-256 prefix)
# ---------------------------------------------------------------------------

def test_version_is_deterministic_across_loads():
    ctx_a = load()
    ctx_b = load()
    assert ctx_a is not None and ctx_b is not None
    assert ctx_a.version == ctx_b.version
    assert len(ctx_a.version) == 8


def test_version_changes_when_xml_body_changes(tmp_path):
    p1 = tmp_path / "ctx1.xml"
    p2 = tmp_path / "ctx2.xml"
    p1.write_text("<team_context><team><name>A</name></team></team_context>", encoding="utf-8")
    p2.write_text("<team_context><team><name>B</name></team></team_context>", encoding="utf-8")
    ctx1 = load(p1)
    ctx2 = load(p2)
    assert ctx1 is not None and ctx2 is not None
    assert ctx1.version != ctx2.version


# ---------------------------------------------------------------------------
# Graceful failure modes — non-fatal, return None, log a warning
# ---------------------------------------------------------------------------

def test_missing_file_returns_none_and_warns(tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        result = load(tmp_path / "does-not-exist.xml")
    assert result is None
    assert any("file not found" in rec.message for rec in caplog.records)


def test_malformed_xml_returns_none_and_warns(tmp_path, caplog):
    p = tmp_path / "broken.xml"
    p.write_text("<not><closed>tags", encoding="utf-8")
    with caplog.at_level(logging.WARNING):
        result = load(p)
    assert result is None
    assert any("malformed XML" in rec.message for rec in caplog.records)


def test_partial_xml_parses_with_empty_sections(tmp_path):
    """A doc with only <team><name> populated should still load — the open-world
    note documents the lists as non-exhaustive, so missing sections are OK."""
    p = tmp_path / "minimal.xml"
    p.write_text(
        "<team_context><team><name>Mini</name></team></team_context>",
        encoding="utf-8",
    )
    ctx = load(p)
    assert ctx is not None
    assert ctx.team_name == "Mini"
    assert ctx.known_projects == []
    assert ctx.known_technologies == []
    assert ctx.known_topics == []
    assert ctx.extraction_examples == []
    assert ctx.style_guide == {}


# ---------------------------------------------------------------------------
# Path resolution precedence
# ---------------------------------------------------------------------------

def test_env_var_overrides_default(tmp_path, monkeypatch):
    p = tmp_path / "override.xml"
    p.write_text(
        "<team_context><team><name>Overridden</name></team></team_context>",
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_VAR, str(p))
    ctx = load()
    assert ctx is not None
    assert ctx.team_name == "Overridden"


def test_explicit_path_overrides_env(tmp_path, monkeypatch):
    """Explicit arg to load() wins over env var."""
    env_file = tmp_path / "env.xml"
    env_file.write_text(
        "<team_context><team><name>FromEnv</name></team></team_context>",
        encoding="utf-8",
    )
    monkeypatch.setenv(ENV_VAR, str(env_file))
    explicit_file = tmp_path / "explicit.xml"
    explicit_file.write_text(
        "<team_context><team><name>FromArg</name></team></team_context>",
        encoding="utf-8",
    )
    ctx = load(explicit_file)
    assert ctx is not None
    assert ctx.team_name == "FromArg"


# ---------------------------------------------------------------------------
# Sanity on the parsed structure for downstream consumers
# ---------------------------------------------------------------------------

def test_known_projects_carry_aliases(tmp_path):
    p = tmp_path / "aliased.xml"
    p.write_text(
        '<team_context><known_projects>'
        '<project name="DStack" aliases="D-Stack,dstack">A stack.</project>'
        '</known_projects></team_context>',
        encoding="utf-8",
    )
    ctx = load(p)
    assert ctx is not None
    assert len(ctx.known_projects) == 1
    assert ctx.known_projects[0]["name"] == "DStack"
    assert ctx.known_projects[0]["aliases"] == ["D-Stack", "dstack"]
    assert ctx.known_projects[0]["description"] == "A stack."
