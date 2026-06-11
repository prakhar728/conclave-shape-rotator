"""C1 gate — `sources.py` reader + NormalizedInput contract.

Asserts the contract documented in IMPLEMENTATION_PLAN.md §G1:

- Otter text → segments with verbatim speaker labels (incl. parentheticals
  and anonymous ``Speaker N``), ``end`` = next.start, last ``end`` = None.
- ``members`` excludes ``Speaker N`` but keeps insertion order.
- BOM is stripped by ``read_file``.
- ``provenance.session_id`` slugged from the filename stem.
- VoxTerm/generic JSON shape still readable (so C2 can route ``parse_transcript``
  through ``sources.read_obj`` without breaking the 7 legacy tests).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from transcripts.sources import (
    NormalizedInput,
    _date_from_name,
    _seconds,
    _slug,
    read_file,
    read_obj,
)

FIXTURES = Path(__file__).parent / "fixtures" / "transcripts"
VOXTERM_FIXTURE = Path(__file__).parent / "fixtures" / "voxterm_session.json"


SAMPLE_OTTER = (
    "Shaw  0:00\n"
    "October makes OS,\n"
    "\n"
    "Alex (flashbots?)  0:09\n"
    "So my goal is not to like release this as a product.\n"
    "\n"
    "Speaker 1  1:31\n"
    "Yeah, and so the hope is that.\n"
    "\n"
    "Shaw  2:14\n"
    "Cool.\n"
)


def test_parse_otter_basic_segments_and_timestamps():
    ni = read_obj(SAMPLE_OTTER, source="otter")

    assert ni.source == "otter"
    assert len(ni.segments) == 4

    # Speaker labels pass through verbatim (incl. parenthetical & anonymous).
    assert [s["speaker"] for s in ni.segments] == [
        "Shaw",
        "Alex (flashbots?)",
        "Speaker 1",
        "Shaw",
    ]

    # Start = elapsed seconds from header timestamp.
    assert ni.segments[0]["start"] == 0.0
    assert ni.segments[1]["start"] == 9.0
    assert ni.segments[2]["start"] == 91.0
    assert ni.segments[3]["start"] == 134.0

    # end = next.start; last is None.
    assert ni.segments[0]["end"] == 9.0
    assert ni.segments[1]["end"] == 91.0
    assert ni.segments[2]["end"] == 134.0
    assert ni.segments[3]["end"] is None

    # Body captured.
    assert ni.segments[0]["text"] == "October makes OS,"
    assert ni.segments[1]["text"].startswith("So my goal")


def test_members_excludes_anonymous_and_preserves_insertion_order():
    ni = read_obj(SAMPLE_OTTER, source="otter")
    # "Shaw" appears twice; only once in members. "Speaker 1" excluded.
    assert ni.provenance["members"] == ["Shaw", "Alex (flashbots?)"]


def test_seconds_supports_m_ss_mm_ss_and_h_mm_ss():
    assert _seconds("0:03") == 3.0
    assert _seconds("12:34") == 754.0
    assert _seconds("1:02:03") == 3723.0


def test_read_file_strips_bom_and_records_provenance(tmp_path):
    # File with UTF-8 BOM; one valid header so we know parsing reached body.
    p = tmp_path / "Standup_May_20.txt"
    p.write_bytes(b"\xef\xbb\xbfShaw  0:00\nhello\n\n")
    ni = read_file(p)

    assert ni.source == "otter"
    assert ni.segments[0]["speaker"] == "Shaw"
    assert ni.segments[0]["text"] == "hello"
    assert ni.provenance["file_path"] == str(p)
    assert ni.provenance["session_id"] == "standup-may-20"
    # Filename carries a date → preferred over mtime.
    assert ni.provenance["date"].endswith("-05-20")


def test_read_file_falls_back_to_mtime_when_filename_has_no_date(tmp_path):
    p = tmp_path / "office-hours-transcript.txt"
    p.write_text("Shaw  0:00\nhi\n\n", encoding="utf-8")
    ni = read_file(p)
    # mtime is always parseable → some ISO date present.
    assert ni.provenance["date"]
    assert ni.provenance["session_id"] == "office-hours-transcript"


def test_date_from_name_recognizes_common_filename_shapes():
    assert _date_from_name("Friday Shaw & Greg Transcript_May_22").endswith("-05-22")
    assert _date_from_name("Day 1 Project Intros Notes May 19 2026") == "2026-05-19"
    assert _date_from_name("no date here") is None


def test_slug_handles_punctuation_and_unicode():
    assert _slug("dstack hangout Alex Shaw Lsdan Andrew") == "dstack-hangout-alex-shaw-lsdan-andrew"
    assert _slug("May 26, wikigen, crossroads") == "may-26-wikigen-crossroads"


def test_read_real_otter_fixture_round_trips():
    """The 13 real cohort transcripts are committable fixtures (§M.9)."""
    p = FIXTURES / "dstack hangout Alex Shaw Lsdan Andrew.txt"
    if not p.exists():
        pytest.skip("real cohort transcript not present (gitignored)")
    ni = read_file(p)
    assert ni.source == "otter"
    assert len(ni.segments) > 10
    # Real labels: plain, parenthetical, and at least one anonymous.
    speakers = [s["speaker"] for s in ni.segments]
    assert "Shaw" in speakers
    assert any(s.startswith("Alex (") for s in speakers)
    # Members: real names only, no "Speaker N" leaking in.
    assert all(not s.lower().startswith("speaker ") for s in ni.provenance["members"])
    assert "Shaw" in ni.provenance["members"]


# ---------------------------------------------------------------------------
# JSON path — required so C2 can route parse_transcript through read_obj.
# ---------------------------------------------------------------------------

def _voxterm_raw() -> dict:
    with open(VOXTERM_FIXTURE, encoding="utf-8") as f:
        return json.load(f)


def test_read_obj_voxterm_batch():
    ni = read_obj(_voxterm_raw())
    assert ni.source == "voxterm"
    # `t` collapses into `start`; `end` stays None on VoxTerm shape.
    seg0 = ni.segments[0]
    assert seg0["speaker"] == "speaker_1"
    assert seg0["start"] == 2.1
    assert seg0["end"] is None
    assert len(ni.segments) == 4
    # Provenance carries VoxTerm fields straight through.
    assert ni.provenance["record_id"] == "transcript-2026-05-27-1430-voxterm"
    assert ni.provenance["session_id"] == "transcript-2026-05-27-1430-voxterm"
    assert ni.provenance["origin_device"].startswith("b0c1d2e3")
    assert ni.provenance["location"] == "cohort-room-2"
    assert ni.provenance["date"] == "2026-05-27"


def test_read_obj_bare_generic_segment_list():
    raw = [
        {"speaker": "speaker_1", "start": 0.0, "end": 3.2, "text": "Hello."},
        {"speaker": "speaker_2", "start": 3.5, "end": 6.0, "text": "Hi."},
        {"speaker": "speaker_1", "start": 6.1, "end": 6.1, "text": "   "},
    ]
    ni = read_obj(raw)
    # source unknown for a bare list (no record_id / origin_device hints).
    assert ni.source == "unknown"
    # Blank-text segment dropped at normalization.
    assert len(ni.segments) == 2
    assert ni.segments[0]["end"] == 3.2


def test_read_obj_multiple_voxterm_batches_concat_in_order():
    raw = [
        {"record_id": "r1", "batch_index": 1, "origin_device": "d", "segments": [
            {"t": 10, "speaker": "speaker_1", "text": "second"}
        ]},
        {"record_id": "r1", "batch_index": 0, "origin_device": "d", "segments": [
            {"t": 1, "speaker": "speaker_1", "text": "first"}
        ]},
    ]
    ni = read_obj(raw)
    assert [s["text"] for s in ni.segments] == ["first", "second"]
    assert ni.provenance["record_id"] == "r1"
