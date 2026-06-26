"""P4 atomic cutover: identify_meeting routes in-person identity by the CONCLAVE_INPERSON_VIA_CAPTURE
flag — capture's own spans → VFTE /v1/identify-spans (new) vs FPM /v1/diarize re-diarization (legacy).

Pure unit test with fakes (no FPM, no audio decode, no DB): asserts the flag picks the right client call,
that the new path derives spans from the meeting's own diarization, and that resolved_speakers gets the
voted voiceprint_id either way.
"""
import types

import pytest

from connectors.capture import identify as idmod


class _Seg:
    def __init__(self, start, end, speaker):
        self.start, self.end, self.speaker = start, end, speaker


class _Meta:
    def __init__(self):
        self.resolved_speakers = {}

    def model_copy(self, update):
        m = _Meta()
        m.resolved_speakers = update.get("resolved_speakers", self.resolved_speakers)
        return m


class _Session:
    def __init__(self):
        self.raw_diarization = [_Seg(0.0, 4.0, "speaker0"), _Seg(4.0, 8.0, "speaker1"),
                                _Seg(8.0, 12.0, "speaker0")]
        self.metadata = _Meta()


@pytest.fixture
def wiring(monkeypatch):
    calls = {"identify_spans": None, "diarize_audio": None, "set_metadata": None}

    async def fake_identify_spans(ws, audio, spans, *, tag="offline"):
        calls["identify_spans"] = {"ws": ws, "spans": spans, "tag": tag}
        # VFTE returns identity per span (speaker0 → Alice, speaker1 → anon)
        return [{"start": s["start"], "end": s["end"], "local_speaker": s["local_speaker"],
                 "voiceprint_id": "vp_A" if s["local_speaker"] == "speaker0" else "vp_B",
                 "name": "Alice" if s["local_speaker"] == "speaker0" else None}
                for s in spans]

    async def fake_diarize_audio(ws, audio, *, tag="offline"):
        calls["diarize_audio"] = {"ws": ws, "tag": tag}
        return [{"start": 0.0, "end": 4.0, "voiceprint_id": "vp_A", "name": "Alice"}]

    fake_fpm = types.SimpleNamespace(identify_spans=fake_identify_spans, diarize_audio=fake_diarize_audio)
    session = _Session()
    fake_store = types.SimpleNamespace(
        load_session=lambda sid: session,
        set_metadata=lambda sid, md: calls.__setitem__("set_metadata", md),
    )
    monkeypatch.setitem(__import__("sys").modules, "infra.fpm_consent", fake_fpm)
    monkeypatch.setitem(__import__("sys").modules, "transcripts.store", fake_store)
    monkeypatch.setattr(idmod, "_assemble_audio", lambda nid: b"RIFFfakeaudio")
    return calls, session


async def _run(flag, monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "inperson_via_capture", flag)
    await idmod.identify_meeting("sess1", "meet1", "ws1")


@pytest.mark.asyncio
async def test_flag_on_uses_identify_spans_from_capture_diarization(wiring, monkeypatch):
    calls, session = wiring
    await _run(True, monkeypatch)
    assert calls["diarize_audio"] is None, "must NOT re-diarize when flag is on"
    assert calls["identify_spans"] is not None
    spans = calls["identify_spans"]["spans"]
    # spans derived from the meeting's own diarization labels
    assert {s["local_speaker"] for s in spans} == {"speaker0", "speaker1"}
    # resolved_speakers got the voted voiceprint_id + name
    md = calls["set_metadata"]
    assert md.resolved_speakers["speaker0"]["voiceprint_id"] == "vp_A"
    assert md.resolved_speakers["speaker0"]["name"] == "Alice"
    assert md.resolved_speakers["speaker1"]["voiceprint_id"] == "vp_B"


@pytest.mark.asyncio
async def test_flag_off_uses_legacy_diarize(wiring, monkeypatch):
    calls, _ = wiring
    await _run(False, monkeypatch)
    assert calls["identify_spans"] is None, "must NOT call identify-spans when flag is off"
    assert calls["diarize_audio"] is not None, "legacy rollback path re-diarizes"


@pytest.mark.asyncio
async def test_flag_on_no_spans_skips(wiring, monkeypatch):
    calls, session = wiring
    session.raw_diarization = []          # nothing diarized → nothing to identify
    await _run(True, monkeypatch)
    assert calls["identify_spans"] is None and calls["set_metadata"] is None
