"""Note-2 fix — the manual-Stop ingest path also links the calendar event.

Drives api.bot_routes._ingest_from_recato_now with its Recato fetch /
translation / store externals stubbed, and asserts link_completed_meeting
is invoked (same enrichment the webhook does), so stopping a bot by hand
behaves identically to a naturally-ended meeting.
"""
from __future__ import annotations

import httpx
import pytest


class _FakeResp:
    status_code = 200

    def json(self):
        return {"segments": [{"text": "hi", "speaker": "A"}]}


@pytest.fixture
def stubbed(monkeypatch):
    monkeypatch.setenv("CAPTURE_API_BASE_URL", "http://recato.test")
    monkeypatch.setenv("CAPTURE_API_TOKEN", "tok")

    # Recato transcript fetch → non-empty segments on the first try.
    monkeypatch.setattr(httpx, "get", lambda *a, **k: _FakeResp())

    import connectors.capture.translator as tr
    monkeypatch.setattr(
        tr, "to_canonical",
        lambda vexa, source: {"meeting": {"external_id": "abc-defg-hij"}},
    )

    # Pretend the session already exists so we skip the build+enrich thread
    # and land directly on the workspace-bind + linking tail.
    from transcripts import store as ts

    class _Sess:
        session_id = "sess-1"

    monkeypatch.setattr(ts, "load_session", lambda ext: _Sess())
    monkeypatch.setattr(ts, "set_workspace", lambda **k: None)

    # Spy on the calendar linking step.
    import infra.meeting_calendar_links as mcl
    calls = []
    monkeypatch.setattr(mcl, "link_completed_meeting",
                        lambda **kw: calls.append(kw))
    return calls


def test_stop_path_links_calendar_event(stubbed):
    from api.bot_routes import _ingest_from_recato_now
    _ingest_from_recato_now("abc-defg-hij", inviter_user_id="u1", workspace_id="ws1")
    assert stubbed == [
        {"meet_code": "abc-defg-hij", "session_id": "sess-1", "inviter_user_id": "u1"}
    ]


def test_stop_path_link_failure_is_swallowed(stubbed, monkeypatch):
    # Linking blowing up must not break the stop flow.
    import infra.meeting_calendar_links as mcl

    def _boom(**kw):
        raise RuntimeError("calendar down")

    monkeypatch.setattr(mcl, "link_completed_meeting", _boom)
    from api.bot_routes import _ingest_from_recato_now
    # Should not raise.
    _ingest_from_recato_now("abc-defg-hij", inviter_user_id="u1", workspace_id="ws1")
