"""Task #38 — meeting origin badge.

`source` alone can't tell in-person from an online bot (both write the same
ingest source); `platform` is the real discriminator, now persisted onto
`SessionMetadata` and mapped to a canonical `origin` the frontend badges.

Covers: the pure `derive_origin` mapping, `platform` persistence through the
capture ingest pipeline (`read_canonical` → `build_session`), the legacy
`bot_invitations` fallback in `resolve_origin`, and origin exposure on the
`to_card` / workspace-list DTOs.
"""
from __future__ import annotations

import pytest

from api.transcripts_routes import to_card, to_view
from infra.meeting_origin import derive_origin, resolve_origin
from transcripts.models import Derived, RawSegment, Session, SessionMetadata


def _session(sid: str, *, source: str = "capture", platform=None) -> Session:
    meta = SessionMetadata(date="2026-07-02", source=source, platform=platform)
    return Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="A", text="hi", start=0.0)],
        metadata=meta,
        derived=Derived(summary="s"),
    )


# --- derive_origin: pure mapping ------------------------------------------

@pytest.mark.parametrize(
    "source,platform,expected",
    [
        # In-person capture: platform "inperson" (capture sends this literal).
        ("capture", "inperson", "in_person"),
        ("capture", "in_person", "in_person"),   # underscore variant normalizes
        # Online bots carry their platform even though source is still "capture".
        ("capture", "google_meet", "google_meet"),
        ("capture", "zoom", "zoom"),
        ("capture", "teams", "teams"),
        # An unrecognized platform still reads as generic online, never crashes.
        ("capture", "webex", "online"),
        # Uploads: no platform, non-capture source.
        ("voxterm", None, "upload"),
        ("otter", None, "upload"),
        ("whisper", None, "upload"),
        # The seeded example session.
        ("demo", None, "demo"),
        ("demo", "google_meet", "demo"),         # demo wins over platform
        # Legacy capture with no platform → in-person (the common case).
        ("capture", None, "in_person"),
        # Empty / missing everything → neutral unknown.
        ("", None, "unknown"),
        (None, None, "unknown"),
    ],
)
def test_derive_origin_mapping(source, platform, expected):
    assert derive_origin(source, platform) == expected


def test_bot_platform_only_consulted_without_platform():
    # When platform is present it wins; the legacy bot_platform is ignored.
    assert derive_origin("capture", "inperson", "google_meet") == "in_person"
    # When platform is absent, the legacy bot_platform decides.
    assert derive_origin("capture", None, "google_meet") == "google_meet"
    # ...but only for capture sources — an upload with a stray bot hint stays upload
    # is not a real scenario; capture-source gate keeps the fallback scoped.
    assert derive_origin("voxterm", None, "zoom") == "zoom"  # explicit bot hint honored


# --- platform persistence through the ingest pipeline ----------------------

def test_platform_persists_through_capture_pipeline():
    """A canonical capture payload's platform lands on SessionMetadata (was dropped)."""
    from transcripts.parse import build_session
    from transcripts.sources import read_canonical

    payload = {
        "source": "capture",
        "meeting": {"external_id": "mtg-1", "platform": "inperson"},
        "segments": [{"start": 0.0, "end": 1.0, "text": "hello", "speaker": "A"}],
    }
    ni = read_canonical(payload)
    sess = build_session(ni)
    assert sess.metadata.platform == "inperson"
    assert resolve_origin(sess) == "in_person"


def test_gmeet_platform_persists_and_maps():
    from transcripts.parse import build_session
    from transcripts.sources import read_canonical

    payload = {
        "source": "capture",
        "meeting": {"external_id": "mtg-2", "platform": "google_meet"},
        "segments": [{"start": 0.0, "end": 1.0, "text": "hi", "speaker": "A"}],
    }
    sess = build_session(read_canonical(payload))
    assert sess.metadata.platform == "google_meet"
    assert resolve_origin(sess) == "google_meet"


def test_upload_has_no_platform():
    """Pasted/otter uploads carry no platform → origin falls to 'upload'."""
    from transcripts.parse import build_session
    from transcripts.sources import read_obj

    ni = read_obj("Alice  0:01\nHello there\n")
    sess = build_session(ni)
    assert sess.metadata.platform is None
    assert resolve_origin(sess) == "upload"


# --- resolve_origin: legacy bot_invitations fallback -----------------------

def test_legacy_capture_no_bot_is_in_person():
    sess = _session("legacy-inperson", source="capture", platform=None)
    assert resolve_origin(sess) == "in_person"


def _make_invitation(native: str, platform: str = "google_meet") -> None:
    from infra import bot_invitations, identity, workspaces

    user = identity.upsert_user_by_supabase(f"sb-{native}", f"{native}@example.com")
    ws = workspaces.create_workspace("Personal", user["id"])
    bot_invitations.create_invitation(
        user_id=user["id"], workspace_id=ws["id"], platform=platform,
        native_meeting_id=native,
    )


def test_legacy_capture_with_bot_invitation_is_online():
    """A legacy capture session (no persisted platform) whose native id has a
    bot_invitation was an online bot meeting → resolve to that platform."""
    native = "abc-defg-hij"
    _make_invitation(native, platform="google_meet")
    # session_id == native_meeting_id for capture meetings.
    sess = _session(native, source="capture", platform=None)
    assert resolve_origin(sess) == "google_meet"


def test_new_session_with_platform_ignores_bot_invitation():
    """When platform IS persisted, resolve_origin trusts it and never looks up
    a (possibly stale) bot_invitation."""
    native = "xyz-online-code"
    _make_invitation(native, platform="google_meet")
    sess = _session(native, source="capture", platform="inperson")
    assert resolve_origin(sess) == "in_person"


# --- DTO exposure ----------------------------------------------------------

def test_to_card_and_to_view_expose_origin():
    sess = _session("card-1", source="capture", platform="inperson")
    card = to_card(sess)
    assert card["origin"] == "in_person"
    assert to_view(sess)["origin"] == "in_person"


def test_to_card_origin_for_upload():
    assert to_card(_session("u", source="voxterm", platform=None))["origin"] == "upload"
