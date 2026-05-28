"""Per-team domain priors + few-shot examples spliced into the enrich prompt.

`IMPLEMENTATION_PLAN.md` v1 §2. The team-context XML is a **static curation
artifact** the adopter maintains — known projects, technologies, topics,
extraction examples — that the model can't infer from a transcript alone.
It's an *inbound configuration* channel, not an ingest channel.

This module owns the loader. The prompt-side splice happens in
`transcripts/prompts.py` (V3). The schema slot to stamp the version onto
each enriched session — `SessionMetadata.team_context_version` — exists
already (V1).

Boundary commitment (v1 §2.3): the XML is OK to include project names,
tech vocab, topic taxonomy, style examples. It is NOT OK to include
current standings, recent decisions from other meetings, live progress
trackers — that's Phase 2 graph territory and leaking it back into
per-meeting extraction breaks the "works for every team" property.

Failures are non-fatal: a missing or malformed file → `load()` returns
`None`, the prompt splice degrades to "no team context" gracefully (the
model still works, just without grounding).
"""
from __future__ import annotations

import hashlib
import logging
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)


#: Env var override; when unset, falls back to the shipped example file
#: so the demo works out of the box.
ENV_VAR = "CONCLAVE_TEAM_CONTEXT"

#: Shipped Shape-Rotator-cohort example. Adopters copy and edit.
_DEFAULT_PATH = Path(__file__).resolve().parent / "team_context.example.xml"


@dataclass
class TeamContext:
    """Parsed contents of a team-context XML file.

    The structured fields are exposed for tests and possible future use;
    the prompt splice path uses :meth:`to_prompt_fragment` which returns
    the raw XML body verbatim. Letting the model see the XML structure
    (rather than a re-serialized projection) keeps the doc the adopter
    maintains and the prompt the model sees aligned — transparency =
    adoption.
    """

    raw_xml: str
    team_name: str = ""
    domain: str = ""
    known_projects: list[dict] = field(default_factory=list)
    known_technologies: list[dict] = field(default_factory=list)
    known_topics: list[str] = field(default_factory=list)
    extraction_examples: list[dict] = field(default_factory=list)
    style_guide: dict[str, str] = field(default_factory=dict)
    open_world_note: str = ""

    @property
    def version(self) -> str:
        """SHA-256 prefix (first 8 chars) of the raw XML body.

        Stamped onto every enriched session via
        ``SessionMetadata.team_context_version`` so A/B-tests across XML
        revisions show up as a distinct backfill key without conflating
        with prompt-version changes.
        """
        return hashlib.sha256(self.raw_xml.encode("utf-8")).hexdigest()[:8]

    def to_prompt_fragment(self) -> str:
        """Render for splicing between the security guard and the JSON contract
        in `SINGLE_SYSTEM` / `CHUNK_SYSTEM` (V3). Adopters reading the XML
        can predict what's in the prompt — same text, no projection."""
        return self.raw_xml


def load(path: Optional[os.PathLike | str] = None) -> Optional[TeamContext]:
    """Load and parse a team-context XML. Returns ``None`` on missing /
    unreadable / malformed, with a logged warning — never raises.

    Path precedence: explicit arg > ``CONCLAVE_TEAM_CONTEXT`` env > shipped
    ``team_context.example.xml``.
    """
    p = _resolve_path(path)
    if not p.is_file():
        log.warning("team_context: file not found at %s — prompts will run "
                    "without grounding. Adopters should set %s.", p, ENV_VAR)
        return None
    try:
        raw_xml = p.read_text(encoding="utf-8")
    except OSError as exc:
        log.warning("team_context: cannot read %s (%s) — running without grounding.", p, exc)
        return None
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        log.warning("team_context: malformed XML in %s (%s) — running without grounding.", p, exc)
        return None
    return _parse(raw_xml, root)


def _resolve_path(explicit: Optional[os.PathLike | str]) -> Path:
    if explicit is not None:
        return Path(explicit)
    env_value = os.environ.get(ENV_VAR, "").strip()
    if env_value:
        return Path(env_value)
    return _DEFAULT_PATH


def _parse(raw_xml: str, root: ET.Element) -> TeamContext:
    """Best-effort structured extraction. Missing sections are silently
    treated as empty — the file's open-world note says the lists are
    non-exhaustive, so the parser shouldn't fail on a partial doc."""
    team_el = root.find("team")
    team_name = (team_el.findtext("name") if team_el is not None else "") or ""
    domain = (team_el.findtext("domain") if team_el is not None else "") or ""

    known_projects: list[dict] = []
    for proj in root.findall(".//known_projects/project"):
        known_projects.append({
            "name": (proj.attrib.get("name") or "").strip(),
            "aliases": [a.strip() for a in (proj.attrib.get("aliases") or "").split(",") if a.strip()],
            "description": (proj.text or "").strip(),
        })

    known_technologies: list[dict] = []
    for tech in root.findall(".//known_technologies/tech"):
        known_technologies.append({
            "name": (tech.attrib.get("name") or "").strip(),
            "kind": (tech.attrib.get("kind") or "").strip(),
            "description": (tech.text or "").strip(),
        })

    known_topics: list[str] = [
        (t.text or "").strip()
        for t in root.findall(".//known_topics/topic")
        if (t.text or "").strip()
    ]

    extraction_examples: list[dict] = []
    for ex in root.findall(".//extraction_examples/example"):
        extraction_examples.append({
            "chunk": (ex.findtext("chunk") or "").strip(),
            "expected": (ex.findtext("expected") or "").strip(),
        })

    style_guide: dict[str, str] = {}
    for kind_el in root.findall(".//style_guide/kind"):
        name = (kind_el.attrib.get("name") or "").strip()
        if name:
            style_guide[name] = (kind_el.text or "").strip()

    open_world_note = (root.findtext("open_world_note") or "").strip()

    return TeamContext(
        raw_xml=raw_xml.strip(),
        team_name=team_name.strip(),
        domain=domain.strip(),
        known_projects=known_projects,
        known_technologies=known_technologies,
        known_topics=known_topics,
        extraction_examples=extraction_examples,
        style_guide=style_guide,
        open_world_note=open_world_note,
    )
