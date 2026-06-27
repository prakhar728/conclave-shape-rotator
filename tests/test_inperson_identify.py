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
    def __init__(self, start, end, speaker, text="hi"):
        self.start, self.end, self.speaker, self.text = start, end, speaker, text


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
    # Patch the real modules' functions (setattr) rather than swapping sys.modules entries — robust to
    # import order (`from transcripts import store` binds the package attr, which a sys.modules swap misses).
    import infra.fpm_consent as fpm
    import transcripts.store as store
    calls = {"identify_spans": None, "diarize_audio": None, "set_metadata": None, "set_raw": None}

    async def fake_identify_spans(ws, audio, spans, *, tag="offline"):
        calls["identify_spans"] = {"ws": ws, "spans": spans, "tag": tag}
        return [{"start": s["start"], "end": s["end"], "local_speaker": s["local_speaker"],
                 "voiceprint_id": "vp_A" if s["local_speaker"] == "speaker0" else "vp_B",
                 "name": "Alice" if s["local_speaker"] == "speaker0" else None}
                for s in spans]

    async def fake_diarize_audio(ws, audio, *, tag="offline"):
        calls["diarize_audio"] = {"ws": ws, "tag": tag}
        return [{"start": 0.0, "end": 4.0, "voiceprint_id": "vp_A", "name": "Alice"}]

    session = _Session()
    monkeypatch.setattr(fpm, "identify_spans", fake_identify_spans)
    monkeypatch.setattr(fpm, "diarize_audio", fake_diarize_audio)
    monkeypatch.setattr(store, "load_session", lambda sid: session)
    monkeypatch.setattr(store, "set_metadata", lambda sid, md: calls.__setitem__("set_metadata", md))
    monkeypatch.setattr(store, "set_raw_diarization", lambda sid, segs: calls.__setitem__("set_raw", segs))
    monkeypatch.setattr(idmod, "_assemble_audio", lambda nid: b"RIFFfakeaudio")
    return calls, session


async def _run(flag, monkeypatch, diarize_url=""):
    from config import settings
    monkeypatch.setattr(settings, "inperson_via_capture", flag)
    monkeypatch.setattr(settings, "diarize_url", diarize_url)
    await idmod.identify_meeting("sess1", "meet1", "ws1")


@pytest.mark.asyncio
async def test_flag_on_no_diarize_url_falls_back_to_diart_spans(wiring, monkeypatch):
    # finalizer URL unset → use capture's own (diart) spans from raw_diarization
    calls, session = wiring
    await _run(True, monkeypatch, diarize_url="")
    assert calls["diarize_audio"] is None, "must NOT re-diarize via FPM when flag is on"
    assert calls["identify_spans"] is not None
    spans = calls["identify_spans"]["spans"]
    assert {s["local_speaker"] for s in spans} == {"speaker0", "speaker1"}   # diart's own labels
    md = calls["set_metadata"]
    assert md.resolved_speakers["speaker0"]["voiceprint_id"] == "vp_A"
    assert md.resolved_speakers["speaker0"]["name"] == "Alice"


@pytest.mark.asyncio
async def test_flag_on_with_diarize_url_uses_authoritative_diarizen(wiring, monkeypatch):
    # finalizer A: the AUTHORITATIVE spans come from the DiariZen post engine, not diart.
    calls, session = wiring
    from connectors.capture import diarize_client

    async def fake_diarize_recording(audio, *, filename="meeting.wav", workspace=""):
        calls["diarize_recording"] = {"workspace": workspace, "bytes": len(audio)}
        return [{"start": 0.0, "end": 4.0, "local_speaker": "speaker0"},
                {"start": 4.0, "end": 8.0, "local_speaker": "speaker1"}]

    monkeypatch.setattr(diarize_client, "diarize_recording", fake_diarize_recording)
    await _run(True, monkeypatch, diarize_url="http://localhost:8086")
    assert calls.get("diarize_recording") is not None, "must call the DiariZen post engine"
    assert calls["diarize_audio"] is None
    assert calls["identify_spans"] is not None
    # AUTHORITATIVE: raw_diarization is OVERWRITTEN with the re-attributed segments (DiariZen replaces diart)
    raw = calls["set_raw"]
    assert raw is not None, "must overwrite raw_diarization with the authoritative result"
    assert len(raw) == 3 and all("text" in s and "speaker" in s for s in raw)   # text preserved, re-labeled
    assert raw[0]["speaker"] == "speaker0" and raw[1]["speaker"] == "speaker1"   # by DiariZen overlap
    # resolved_speakers keyed by DiariZen labels + names
    md = calls["set_metadata"]
    assert md.resolved_speakers["speaker0"]["voiceprint_id"] == "vp_A"
    assert md.resolved_speakers["speaker0"]["name"] == "Alice"


@pytest.mark.asyncio
async def test_flag_on_no_url_does_not_overwrite_raw(wiring, monkeypatch):
    # diart fallback (no DiariZen URL) → identity votes onto diart labels, but raw is NOT overwritten.
    calls, _ = wiring
    await _run(True, monkeypatch, diarize_url="")
    assert calls["set_raw"] is None, "diart fallback must NOT overwrite the live transcript"
    assert calls["set_metadata"] is not None   # still resolves names onto diart labels


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
