"""Task #13 — lazy heal-on-open after a DEFERRED speaker-name confirm.

When a speaker is tagged and their consent lands later (out-of-band, no Conclave
event), the meeting summary heals the next time the meeting is opened: the
read path compares the currently-resolved speaker-name set against the stamp the
summary was built with, and on a real difference (≥1 confirmed name) enqueues a
background re-enrich that projects the real names into the LLM input — that
meeting only.

Covers TASK-13 §6: heal-on-open, no-op-when-unchanged, pending-excluded,
idempotent/no-loop, no-double-fire, current-meeting-only, projection on/off,
and the #9 approve path re-stamping. The mutation-audit lives in a separate
isolated worktree (a different agent) per the build workflow.
"""
from __future__ import annotations

import json

import pytest

from storage import sqlite
from transcripts import store
from transcripts.enrich import _segments_to_text, enrich_session, transcript_text
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


# ---------------------------------------------------------------------------
# Test doubles + fixtures
# ---------------------------------------------------------------------------

class EchoLLM:
    """Echoes the prompt's user-message body into the summary so the projected
    speaker names are observable in the enrichment output."""

    model_name = "echo-llm"

    def __init__(self):
        self.bodies: list[str] = []

    def invoke(self, messages):
        body = messages[-1].content
        self.bodies.append(body)
        return type("Resp", (), {
            "content": json.dumps({"summary": body, "signals": [], "entities": []})
        })()


@pytest.fixture()
def tmp_db():
    """Clean the transcript tables on the conftest-migrated shared DB (the
    migration-only `transcript_v2` table is absent from a bare `init_db()`)."""
    conn = sqlite._get_conn()
    for table in ("transcript_v2", "transcript_sessions"):
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:  # noqa: BLE001
            pass
    yield


@pytest.fixture()
def spy_enqueue(monkeypatch):
    """Replace enqueue.enrich with a call-recording spy (no real background work)."""
    from connectors.jobs import enqueue
    calls: list[str] = []
    monkeypatch.setattr(enqueue, "enrich", lambda sid, **k: calls.append(sid))
    return calls


def _make(sid: str, resolved: dict, *, summary: str = "old summary") -> Session:
    """A one-speaker session whose raw label is `speaker_1`."""
    return Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="speaker_1", text="we should ship matching", start=0.0)],
        metadata=SessionMetadata(date="2026-06-30", source="record", resolved_speakers=resolved),
        derived=Derived(summary=summary),
    )


def _persist_enriched(sid: str, resolved: dict) -> Session:
    """Save a session, enrich it (stamping enrich_speakers_version against the
    given resolved set), and create its v2 draft — the realistic pre-open state."""
    sess = _make(sid, resolved)
    store.save_session(sess)
    enrich_session(sess, llm=EchoLLM())
    store.set_derived(sid, sess.derived)
    store.set_metadata(sid, sess.metadata)
    store.create_v2_draft(sid)
    return sess


def _confirm_name(sid: str, label: str, name: str) -> None:
    """Simulate an out-of-band consent confirm landing in resolved_speakers."""
    s = store.load_session(sid)
    s.metadata.resolved_speakers[label]["name"] = name
    store.set_metadata(sid, s.metadata)


# ---------------------------------------------------------------------------
# Name projection (§3.3)
# ---------------------------------------------------------------------------

def test_segments_to_text_projects_confirmed_name():
    segs = [RawSegment(speaker="speaker_2", text="I'll own it")]
    assert _segments_to_text(segs) == "[speaker_2] I'll own it"
    assert _segments_to_text(segs, {"speaker_2": "Andrew"}) == "[Andrew] I'll own it"


def test_projection_on_off_changes_enrich_input(tmp_db):
    """§6.7 — projection OFF: summary keeps `speaker_1`; ON: it carries the name."""
    anon = _make("p-off", {"speaker_1": {"voiceprint_id": "vp", "name": None}})
    enrich_session(anon, llm=EchoLLM())
    assert "speaker_1" in anon.derived.summary
    assert "Andrew" not in anon.derived.summary

    named = _make("p-on", {"speaker_1": {"voiceprint_id": "vp", "name": "Andrew"}})
    enrich_session(named, llm=EchoLLM())
    assert "[Andrew]" in named.derived.summary
    assert "speaker_1" not in named.derived.summary


def test_transcript_text_projects_from_resolved_speakers():
    sess = _make("tt", {"speaker_1": {"voiceprint_id": "vp", "name": "Andrew"}})
    assert "[Andrew]" in transcript_text(sess)


def test_raw_diarization_is_not_mutated_by_projection(tmp_db):
    named = _make("immut", {"speaker_1": {"voiceprint_id": "vp", "name": "Andrew"}})
    enrich_session(named, llm=EchoLLM())
    assert named.raw_diarization[0].speaker == "speaker_1"  # label untouched


# ---------------------------------------------------------------------------
# Stamp (§3.1)
# ---------------------------------------------------------------------------

def test_stamp_changes_when_name_appears():
    anon = _make("h", {"speaker_1": {"voiceprint_id": "vp", "name": None}})
    h0 = store.speakers_version(anon)
    anon.metadata.resolved_speakers["speaker_1"]["name"] = "Andrew"
    h1 = store.speakers_version(anon)
    assert h0 != h1
    assert store.speakers_version(anon) == h1  # deterministic


def test_stamp_stable_across_dict_order():
    a = _make("o", {"s1": {"name": "A"}, "s2": {"name": "B"}})
    a.raw_diarization = [RawSegment(speaker="s1", text="x"), RawSegment(speaker="s2", text="y")]
    b = _make("o", {"s2": {"name": "B"}, "s1": {"name": "A"}})
    b.raw_diarization = [RawSegment(speaker="s2", text="y"), RawSegment(speaker="s1", text="x")]
    assert store.speakers_version(a) == store.speakers_version(b)


def test_enrich_session_stamps_speakers_version(tmp_db):
    sess = _make("st", {"speaker_1": {"voiceprint_id": "vp", "name": None}})
    enrich_session(sess, llm=EchoLLM())
    assert sess.metadata.enrich_speakers_version == store.speakers_version(sess)


# ---------------------------------------------------------------------------
# Heal-on-open trigger (§3.2)
# ---------------------------------------------------------------------------

def test_heal_on_open_enqueues_and_marks_stale(tmp_db, spy_enqueue):
    import api.transcripts_routes as routes
    _persist_enriched("m1", {"speaker_1": {"voiceprint_id": "vp1", "name": None}})
    _confirm_name("m1", "speaker_1", "Andrew")  # out-of-band confirm

    needed = routes._maybe_heal_on_open(store.load_session("m1"))

    assert needed is True
    assert spy_enqueue == ["m1"]                       # background re-enrich queued
    assert store.load_v2("m1").insights_stale is True  # badge + dedup lock set


def test_heal_summary_carries_the_name(tmp_db, monkeypatch):
    """End-to-end through the actual re-enrich primitive #13 reuses (enqueue.enrich
    → `_enrich_in_background`): confirm out-of-band → re-enrich projects the real
    name, re-stamps, and clears the stale lock. The KB build + email blast are
    stubbed (isolated from this unit, as in test_insights_stale)."""
    import api.transcripts_routes as routes
    import transcripts.enrich as enrich_mod

    _persist_enriched("m1b", {"speaker_1": {"voiceprint_id": "vp", "name": None}})
    assert "speaker_1" in store.load_session("m1b").derived.summary  # anonymous initially
    _confirm_name("m1b", "speaker_1", "Andrew")  # out-of-band confirm
    store.mark_insights_stale("m1b")  # as the heal trigger would, before enqueue

    # Inject the FakeLLM + isolate the heavy/global stages so this stays a unit.
    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: False)
    monkeypatch.setattr(enrich_mod, "enrich_session",
                        lambda s, **k: enrich_session(s, llm=EchoLLM()))
    monkeypatch.setattr(routes, "_build_kb", lambda sid: None)
    monkeypatch.setattr(routes, "_send_attendee_magic_links", lambda sid: None)

    routes._enrich_in_background("m1b")

    reloaded = store.load_session("m1b")
    assert "[Andrew]" in reloaded.derived.summary          # regenerated WITH the real name
    assert "speaker_1" not in reloaded.derived.summary
    assert reloaded.metadata.enrich_speakers_version == \
        store.speakers_version(reloaded)                   # re-stamped to current
    assert store.load_v2("m1b").insights_stale is False    # lock cleared → no loop


def test_no_op_when_names_unchanged(tmp_db, spy_enqueue):
    import api.transcripts_routes as routes
    # Enriched WITH the name already present → stamp already reflects it.
    _persist_enriched("m2", {"speaker_1": {"voiceprint_id": "vp", "name": "Andrew"}})

    needed = routes._maybe_heal_on_open(store.load_session("m2"))

    assert needed is False
    assert spy_enqueue == []  # §6.2 — no regen on an unchanged open


def test_pending_tag_excluded(tmp_db, spy_enqueue):
    """§6.3 — a pending tag never lands in resolved_speakers, so the stamp is
    unchanged and no heal fires (only CONFIRMED names heal)."""
    import api.transcripts_routes as routes
    _persist_enriched("m3", {"speaker_1": {"voiceprint_id": "vp", "name": None}})
    # (pending proposal would live in FPM/proposals, NOT resolved_speakers — name stays None)

    needed = routes._maybe_heal_on_open(store.load_session("m3"))

    assert needed is False
    assert spy_enqueue == []


def test_all_anonymous_first_open_no_spurious_regen(tmp_db, spy_enqueue):
    """§6.9(c) guard — an all-anonymous meeting (incl. an unstamped legacy one)
    must NOT regen on its first open."""
    import api.transcripts_routes as routes
    sess = _make("m4", {"speaker_1": {"voiceprint_id": "vp", "name": None}})
    store.save_session(sess)
    store.create_v2_draft("m4")
    # No enrich_speakers_version stamp at all (legacy) AND no confirmed name.
    assert store.load_session("m4").metadata.enrich_speakers_version is None

    needed = routes._maybe_heal_on_open(store.load_session("m4"))

    assert needed is False
    assert spy_enqueue == []


def test_idempotent_no_loop(tmp_db, spy_enqueue):
    """§6.4 — after the re-enrich re-stamps, a second open is a no-op."""
    import api.transcripts_routes as routes
    _persist_enriched("m5", {"speaker_1": {"voiceprint_id": "vp", "name": None}})
    _confirm_name("m5", "speaker_1", "Andrew")

    assert routes._maybe_heal_on_open(store.load_session("m5")) is True
    assert spy_enqueue == ["m5"]

    # Simulate the background re-enrich completing: re-stamp + clear the lock.
    sess = store.load_session("m5")
    enrich_session(sess, llm=EchoLLM())
    store.set_metadata("m5", sess.metadata)
    store.clear_insights_stale("m5")

    # Second open with unchanged names → no-op (no second enqueue, no loop).
    assert routes._maybe_heal_on_open(store.load_session("m5")) is False
    assert spy_enqueue == ["m5"]


def test_no_double_fire_on_concurrent_opens(tmp_db, spy_enqueue):
    """§6.5 — two opens of a stale meeting before the re-enrich finishes →
    exactly one enqueue (the in-flight insights_stale lock dedups the second)."""
    import api.transcripts_routes as routes
    _persist_enriched("m6", {"speaker_1": {"voiceprint_id": "vp", "name": None}})
    _confirm_name("m6", "speaker_1", "Andrew")

    a = routes._maybe_heal_on_open(store.load_session("m6"))
    b = routes._maybe_heal_on_open(store.load_session("m6"))  # concurrent, lock held

    assert a is True and b is True       # both show the badge
    assert spy_enqueue == ["m6"]         # but only ONE regen fired


def test_current_meeting_only(tmp_db, spy_enqueue):
    """§6.6 — opening one meeting heals only IT, never the person's other meetings,
    even when they share the same voiceprint."""
    import api.transcripts_routes as routes
    _persist_enriched("open-me", {"speaker_1": {"voiceprint_id": "vpX", "name": None}})
    _persist_enriched("leave-me", {"speaker_1": {"voiceprint_id": "vpX", "name": None}})
    _confirm_name("open-me", "speaker_1", "Andrew")
    _confirm_name("leave-me", "speaker_1", "Andrew")

    routes._maybe_heal_on_open(store.load_session("open-me"))

    assert spy_enqueue == ["open-me"]                         # only the opened one
    assert store.load_v2("leave-me").insights_stale is False  # the other is untouched


def test_name_correction_also_heals(tmp_db, spy_enqueue):
    """A corrected name (Andrew → Andrew Smith) flips the hash and heals too."""
    import api.transcripts_routes as routes
    _persist_enriched("m7", {"speaker_1": {"voiceprint_id": "vp", "name": "Andrew"}})
    _confirm_name("m7", "speaker_1", "Andrew Smith")

    assert routes._maybe_heal_on_open(store.load_session("m7")) is True
    assert spy_enqueue == ["m7"]


def test_failed_heal_releases_lock_and_retries(tmp_db, spy_enqueue, monkeypatch):
    """H4 — a FAILED re-enrich (LLM down) must release the in-flight lock AND leave the
    stamp diverged, so the next open re-fires the heal (retry). Without this the lock
    (which doubles as the dedup key) never releases → stuck badge + permanent no-retry."""
    import api.transcripts_routes as routes
    import transcripts.enrich as enrich_mod

    _persist_enriched("h4", {"speaker_1": {"voiceprint_id": "vp", "name": None}})
    stamp_before = store.load_session("h4").metadata.enrich_speakers_version
    _confirm_name("h4", "speaker_1", "Andrew")
    store.mark_insights_stale("h4")  # as the heal trigger does before enqueue

    # The re-enrich blows up (LLM unreachable). enrich_session throws BEFORE stamping.
    def boom(s, **k):
        raise RuntimeError("LLM 502 — gateway down")
    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: False)
    monkeypatch.setattr(enrich_mod, "enrich_session", boom)
    monkeypatch.setattr(routes, "_build_kb", lambda sid: None)
    monkeypatch.setattr(routes, "_send_attendee_magic_links", lambda sid: None)

    routes._enrich_in_background("h4")

    s = store.load_session("h4")
    assert s.metadata.enrichment_status == "failed"
    assert store.load_v2("h4").insights_stale is False          # lock RELEASED on failure
    assert s.metadata.enrich_speakers_version == stamp_before    # stamp NOT advanced (still diverged)

    # Next open re-fires the heal → retry (not permanently stuck).
    assert routes._maybe_heal_on_open(store.load_session("h4")) is True
    assert spy_enqueue == ["h4"]


def test_skipped_enrich_also_releases_lock(tmp_db, spy_enqueue, monkeypatch):
    """H4 (skip path) — when enrich is skipped (no LLM), the lock still releases and the
    stamp stays diverged, so the heal retries once an LLM is configured (no stuck badge)."""
    import api.transcripts_routes as routes
    _persist_enriched("h4s", {"speaker_1": {"voiceprint_id": "vp", "name": None}})
    stamp_before = store.load_session("h4s").metadata.enrich_speakers_version
    _confirm_name("h4s", "speaker_1", "Andrew")
    store.mark_insights_stale("h4s")

    monkeypatch.setattr(routes, "_should_skip_enrich", lambda: True)  # LLM disabled
    monkeypatch.setattr(routes, "_build_kb", lambda sid: None)
    monkeypatch.setattr(routes, "_send_attendee_magic_links", lambda sid: None)

    routes._enrich_in_background("h4s")

    assert store.load_session("h4s").metadata.enrichment_status == "skipped"
    assert store.load_v2("h4s").insights_stale is False                       # lock released
    assert store.load_session("h4s").metadata.enrich_speakers_version == stamp_before
    assert routes._maybe_heal_on_open(store.load_session("h4s")) is True      # retries
    assert spy_enqueue == ["h4s"]


# ---------------------------------------------------------------------------
# #9 approve path re-stamps (§3.8)
# ---------------------------------------------------------------------------

def test_approve_restamps_so_no_immediate_reheal(tmp_db, spy_enqueue, monkeypatch):
    """§6.8 — #9's edit→Approve re-derives AND re-stamps enrich_speakers_version
    (from the original raw-label basis), so opening a just-approved meeting does
    NOT immediately re-heal."""
    import api.transcripts_routes as routes
    import transcripts.enrich as enrich_mod

    monkeypatch.setattr(routes, "_build_kb", lambda sid: None)

    def fake_enrich(session, **k):
        session.derived.summary = "re-derived"
        # mimic enrich_session stamping (wrong basis on the v2-name path) — the
        # approve path must override it from the original session.
        session.metadata.enrich_speakers_version = "WRONG-BASIS"

    monkeypatch.setattr(enrich_mod, "enrich_session", fake_enrich)

    # A meeting tagged in the editor (confirmed name on resolved_speakers).
    _persist_enriched("m8", {"speaker_1": {"voiceprint_id": "vp", "name": "Andrew"}})
    store.assign_speaker("m8", 0, "Andrew")  # editor tag → stale draft

    routes.approve_and_build("m8")

    expected = store.speakers_version(store.load_session("m8"))
    assert store.load_session("m8").metadata.enrich_speakers_version == expected
    assert store.load_v2("m8").insights_stale is False

    # Opening it now must NOT re-heal.
    assert routes._maybe_heal_on_open(store.load_session("m8")) is False
    assert spy_enqueue == []
