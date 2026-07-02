"""Task #37 — speaker-turn coalescing (display projection over immutable spans)."""
from __future__ import annotations

from transcripts.turns import PARAGRAPH_GAP_SEC, group_into_turns


def _seg(speaker, text, start, end, **extra):
    return {"speaker": speaker, "text": text, "start": start, "end": end, **extra}


def test_consecutive_same_speaker_spans_become_one_turn():
    segs = [
        _seg("0", "Hello", 0.0, 1.0),
        _seg("0", "there", 1.0, 2.0),
        _seg("0", "friend", 2.0, 3.0),
    ]
    turns = group_into_turns(segs)
    assert len(turns) == 1
    t = turns[0]
    assert t["speaker"] == "0"
    assert t["start"] == 0.0 and t["end"] == 3.0   # span the group
    assert t["text"] == "Hello there friend"        # joined
    assert len(t["spans"]) == 3                      # spans still exposed (clip/edit/seek)


def test_a_speaker_change_starts_a_new_turn():
    segs = [
        _seg("0", "hi", 0.0, 1.0),
        _seg("0", "again", 1.0, 2.0),
        _seg("1", "yo", 2.0, 3.0),
        _seg("0", "back", 3.0, 4.0),
    ]
    turns = group_into_turns(segs)
    assert [t["speaker"] for t in turns] == ["0", "1", "0"]
    assert turns[0]["text"] == "hi again"
    assert turns[1]["text"] == "yo"
    assert turns[2]["text"] == "back"


def test_two_distinct_unknown_speakers_never_merge():
    # Different local labels, no resolved identity → distinct keys → separate turns.
    segs = [_seg("0", "a", 0.0, 1.0), _seg("1", "b", 1.0, 2.0)]
    turns = group_into_turns(segs)
    assert len(turns) == 2


def test_resolved_identity_merges_across_different_local_labels():
    # Same person (same voiceprint) but the diarizer used different local labels in
    # two chunks → keying on the resolved identity merges them into one turn.
    segs = [
        _seg("0", "part one", 0.0, 1.0, voiceprint_id="vp_ada"),
        _seg("3", "part two", 1.0, 2.0, voiceprint_id="vp_ada"),
    ]
    turns = group_into_turns(segs)
    assert len(turns) == 1
    assert turns[0]["voiceprint_id"] == "vp_ada"
    assert turns[0]["text"] == "part one part two"


def test_confirmed_name_is_a_merge_key_but_proposed_name_is_not():
    # Confirmed name merges…
    named = group_into_turns([
        _seg("0", "x", 0.0, 1.0, speaker_name="Ada"),
        _seg("2", "y", 1.0, 2.0, speaker_name="Ada"),
    ])
    assert len(named) == 1
    # …but an unconsented proposed_name must NOT glue two distinct locals together.
    proposed = group_into_turns([
        _seg("0", "x", 0.0, 1.0, proposed_name="Ada"),
        _seg("2", "y", 1.0, 2.0, proposed_name="Ada"),
    ])
    assert len(proposed) == 2


def test_empty_and_whitespace_spans_are_absorbed_not_turn_boundaries():
    segs = [
        _seg("0", "hello", 0.0, 1.0),
        _seg("1", "   ", 1.0, 1.2),   # empty, different speaker → must NOT flip/open
        _seg("0", "world", 1.2, 2.0),
    ]
    turns = group_into_turns(segs)
    assert len(turns) == 1                     # the blank never split the turn
    assert turns[0]["text"] == "hello world"
    assert turns[0]["end"] == 2.0
    assert len(turns[0]["spans"]) == 3          # the blank span is still kept


def test_leading_empty_span_does_not_open_a_turn():
    segs = [_seg("0", "", 0.0, 0.5), _seg("0", "real", 0.5, 1.0)]
    turns = group_into_turns(segs)
    assert len(turns) == 1
    assert turns[0]["text"] == "real"
    assert turns[0]["start"] == 0.5             # opened on the first text-bearing span


def test_big_same_speaker_gap_inserts_paragraph_break_but_one_turn():
    segs = [
        _seg("0", "before the pause", 0.0, 2.0),
        _seg("0", "after the pause", 2.0 + PARAGRAPH_GAP_SEC + 1, 2.0 + PARAGRAPH_GAP_SEC + 3),
    ]
    turns = group_into_turns(segs)
    assert len(turns) == 1                       # still one turn
    assert "\n\n" in turns[0]["text"]            # with a paragraph break


def test_short_gap_joins_with_a_single_space():
    segs = [_seg("0", "a", 0.0, 1.0), _seg("0", "b", 2.0, 3.0)]  # 1s gap < threshold
    turns = group_into_turns(segs)
    assert turns[0]["text"] == "a b"


def test_empty_input():
    assert group_into_turns([]) == []


def test_to_transcript_exposes_turns_alongside_spans():
    from api.transcripts_routes import to_transcript
    from transcripts import store
    from transcripts.models import Derived, RawSegment, Session, SessionMetadata

    sess = Session(
        session_id="t-turns",
        raw_diarization=[
            RawSegment(speaker="0", text="one", start=0.0, end=1.0),
            RawSegment(speaker="0", text="two", start=1.0, end=2.0),
            RawSegment(speaker="1", text="three", start=2.0, end=3.0),
        ],
        metadata=SessionMetadata(date="2026-07-02", source="capture"),
        derived=Derived(summary="s"),
    )
    store.save_session(sess)  # to_transcript re-reads spans via v2_segments_or_raw
    out = to_transcript(sess)
    assert len(out["segments"]) == 3            # spans preserved
    assert len(out["turns"]) == 2               # coalesced (0,0 → one; 1 → one)
    assert out["turns"][0]["text"] == "one two"
    assert len(out["turns"][0]["spans"]) == 2
