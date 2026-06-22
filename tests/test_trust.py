"""Part 1 increment 9a — ramp-up trust state + correction-rate graduation: TS-1/3/6.

State is derived from per-meeting correction counts: a user graduates (gated→auto)
once their avg corrections over the last GRADUATION_WINDOW approved meetings drops
below GRADUATION_THRESHOLD.
"""
from __future__ import annotations

from transcripts import store, trust
from transcripts.models import RawSegment, Session, SessionMetadata


def _meeting(user_id, sid, corrections):
    store.save_session(Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="s", text="hi")],
        metadata=SessionMetadata(date="2026-06-22", source="t"),
    ))
    for _ in range(corrections):
        trust.bump_correction(user_id, sid)
    trust.finalize(user_id, sid)


def test_new_user_is_gated():  # TS-1
    assert trust.state_for("u_new") == "gated"


def test_graduates_when_corrections_low():  # TS-3
    for i, c in enumerate([0, 1, 1]):  # avg 0.67 < 2.0
        _meeting("u_grad", f"g{i}", c)
    assert trust.state_for("u_grad") == "auto"


def test_stays_gated_when_corrections_high():
    for i, c in enumerate([3, 4, 3]):  # avg 3.33 > 2.0
        _meeting("u_high", f"h{i}", c)
    assert trust.state_for("u_high") == "gated"


def test_needs_full_window():  # boundary — 2 meetings < window of 3
    for i, c in enumerate([0, 0]):
        _meeting("u_two", f"t{i}", c)
    assert trust.state_for("u_two") == "gated"


def test_per_user_independent():  # TS-6
    for i, c in enumerate([0, 0, 0]):
        _meeting("u_A", f"a{i}", c)
    assert trust.state_for("u_A") == "auto"
    assert trust.state_for("u_B") == "gated"


def test_finalize_without_corrections_counts_as_zero():
    for i in range(3):
        _meeting("u_clean", f"c{i}", 0)  # approved with no edits
    assert trust.state_for("u_clean") == "auto"  # 0-correction meetings graduate fast
