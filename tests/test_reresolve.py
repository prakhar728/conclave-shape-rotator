"""P4 (Conclave) — reresolve_voiceprint sweep.

A confirmed binding in FPM propagates the name across every stored transcript that
carries the voiceprint_id, by rewriting ONLY resolved_speakers[label]["name"] — never
the label key (the immutable C3 join key) or raw_diarization / Signal.said_by.
"""
from infra import identity, workspaces
from transcripts import store
from transcripts.models import Derived, RawSegment, Session, SessionMetadata, Signal


def _save(sid, resolved, *, said_by=None, ws=None, owner=None):
    raw = [RawSegment(speaker=lbl, text=f"{lbl} said something", start=0.0) for lbl in resolved]
    derived = (Derived(summary="s",
                       signals=[Signal(kind="action_item", text="t", said_by=said_by)])
               if said_by else Derived())
    sess = Session(
        session_id=sid, raw_diarization=raw,
        metadata=SessionMetadata(date="2026-06-14", source="record", resolved_speakers=resolved),
        derived=derived,
    )
    store.save_session(sess)
    if ws:
        store.set_workspace(sid, workspace_id=ws, owner_user_id=owner, visibility="owner-only")
    return sess


def test_sweep_rewrites_name_for_matching_vid():
    _save("rr_one", {"Speaker 1": {"voiceprint_id": "vp_x", "name": None, "confidence": 0.8}})
    n = store.reresolve_voiceprint("vp_x", "Alice")
    assert n == 1
    rs = store.load_session("rr_one").metadata.resolved_speakers
    assert rs["Speaker 1"]["name"] == "Alice"
    assert rs["Speaker 1"]["voiceprint_id"] == "vp_x"  # other fields intact


def test_label_key_and_said_by_untouched():
    _save("rr_c3", {"Speaker 3": {"voiceprint_id": "vp_c3", "name": None, "confidence": 0.9}},
          said_by=["Speaker 3"])
    store.reresolve_voiceprint("vp_c3", "Carla")
    s = store.load_session("rr_c3")
    assert list(s.metadata.resolved_speakers.keys()) == ["Speaker 3"]  # label key unchanged
    assert s.raw_diarization[0].speaker == "Speaker 3"                 # raw segment untouched
    assert s.derived.signals[0].said_by == ["Speaker 3"]              # C3: said_by stays the label


def test_two_sessions_same_vid_both_updated():
    _save("rr_a", {"Speaker 1": {"voiceprint_id": "vp_dup", "name": None, "confidence": 0.7}})
    _save("rr_b", {"Speaker 2": {"voiceprint_id": "vp_dup", "name": None, "confidence": 0.7}})
    n = store.reresolve_voiceprint("vp_dup", "Bob")
    assert n == 2
    assert store.load_session("rr_a").metadata.resolved_speakers["Speaker 1"]["name"] == "Bob"
    assert store.load_session("rr_b").metadata.resolved_speakers["Speaker 2"]["name"] == "Bob"


def test_unrelated_session_unchanged():
    _save("rr_keep", {"Speaker 1": {"voiceprint_id": "vp_other", "name": "Keep", "confidence": 0.5}})
    store.reresolve_voiceprint("vp_target_only", "New")
    assert store.load_session("rr_keep").metadata.resolved_speakers["Speaker 1"]["name"] == "Keep"


def test_other_vid_in_same_session_unchanged():
    _save("rr_mixed", {
        "Speaker 1": {"voiceprint_id": "vp_m1", "name": None, "confidence": 0.6},
        "Speaker 2": {"voiceprint_id": "vp_m2", "name": "Dana", "confidence": 0.6},
    })
    store.reresolve_voiceprint("vp_m1", "Eve")
    rs = store.load_session("rr_mixed").metadata.resolved_speakers
    assert rs["Speaker 1"]["name"] == "Eve"
    assert rs["Speaker 2"]["name"] == "Dana"  # the other voiceprint's name is left alone


def test_legacy_cohort_entry_without_voiceprint_id_ignored():
    _save("rr_legacy", {"Shaw": {"record_id": "shaw-walters", "name": "Shaw", "mock": True}})
    n = store.reresolve_voiceprint("vp_anything", "X")
    assert n == 0
    assert store.load_session("rr_legacy").metadata.resolved_speakers["Shaw"]["name"] == "Shaw"


def test_workspace_scoped_sweep_skips_other_workspaces():
    user = identity.upsert_user_by_supabase("rr-sb", "rr@example.com")
    ws_a = workspaces.create_workspace("RR-A", user["id"])
    ws_b = workspaces.create_workspace("RR-B", user["id"])
    _save("rr_wsA", {"Speaker 1": {"voiceprint_id": "vp_ws", "name": None, "confidence": 0.8}},
          ws=ws_a["id"], owner=user["id"])
    _save("rr_wsB", {"Speaker 1": {"voiceprint_id": "vp_ws", "name": None, "confidence": 0.8}},
          ws=ws_b["id"], owner=user["id"])
    n = store.reresolve_voiceprint("vp_ws", "Frank", workspace_id=ws_a["id"])
    assert n == 1
    assert store.load_session("rr_wsA").metadata.resolved_speakers["Speaker 1"]["name"] == "Frank"
    assert store.load_session("rr_wsB").metadata.resolved_speakers["Speaker 1"]["name"] is None
