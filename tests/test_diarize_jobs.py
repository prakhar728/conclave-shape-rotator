"""Task #16 — diarize finalize SUBMITS (no blocking call) + POST /api/diarize/result reconciles.

GPU-independent: fakeredis for the queue, fakes for VFTE identify-spans + the store (mirrors
`test_inperson_identify.py`'s setattr-on-real-module pattern). Asserts:
  * the finalize submit enqueues a diarize job + creates the `jobs:{id}` hash (no DiariZen HTTP call);
  * the result callback runs identify-spans + reconciles BOTH branches (authoritative overwrite /
    diart-fallback vote);
  * the callback is IDEMPOTENT — a redelivered result applies identity exactly once;
  * the callback chains enrichment (identity-before-enrich ordering preserved).
"""
import fakeredis
import pytest

from connectors.capture import diarize_jobs
from connectors.jobs import queue


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
def r():
    return fakeredis.FakeStrictRedis(decode_responses=True)


@pytest.fixture
def wiring(monkeypatch):
    """Patch VFTE identify-spans, the store, audio assembly, and the enrich chain."""
    import api.diarize_result_routes as dr
    import connectors.capture.identify as idmod
    import infra.fpm_consent as fpm
    import transcripts.store as store
    from connectors.jobs import enqueue

    calls = {"identify_spans": 0, "set_metadata": None, "set_raw": None, "enrich": []}

    async def fake_identify_spans(ws, audio, spans, *, tag="offline", meeting_id=None, host_user=None):
        calls["identify_spans"] += 1
        return [{"start": s["start"], "end": s["end"], "local_speaker": s["local_speaker"],
                 "voiceprint_id": "vp_A" if s["local_speaker"] == "speaker0" else "vp_B",
                 "name": "Alice" if s["local_speaker"] == "speaker0" else None}
                for s in spans]

    session = _Session()
    monkeypatch.setattr(fpm, "identify_spans", fake_identify_spans)
    monkeypatch.setattr(store, "load_session", lambda sid: session)
    monkeypatch.setattr(store, "set_metadata", lambda sid, md: calls.__setitem__("set_metadata", md))
    monkeypatch.setattr(store, "set_raw_diarization", lambda sid, segs: calls.__setitem__("set_raw", segs))
    monkeypatch.setattr(idmod, "_assemble_audio", lambda nid: b"RIFFfakeaudio")
    monkeypatch.setattr(enqueue, "enrich", lambda sid, client=None: calls["enrich"].append(sid))
    return calls, session


# ── finalize submits, never blocks ──────────────────────────────────────────

def test_submit_diarize_job_enqueues_and_records(r, monkeypatch):
    monkeypatch.setattr(diarize_jobs.settings, "audio_fetch_url", "http://conclave/api/diarize/audio")
    monkeypatch.setattr(diarize_jobs.settings, "diarize_result_callback_url", "http://conclave/api/diarize/result")
    job_id = diarize_jobs.submit_diarize_job(session_id="s1", native_meeting_id="meet1",
                                             workspace_id="ws1", client=r)
    assert job_id is not None
    job = queue.get_job(job_id, client=r)
    assert job["type"] == "diarize" and job["status"] == "queued"
    p = job["payload_obj"]
    assert p["session_id"] == "s1" and p["meeting_id"] == "meet1" and p["workspace"] == "ws1"
    assert p["audio_ref"] == "http://conclave/api/diarize/audio/meet1"
    assert p["callback_url"] == "http://conclave/api/diarize/result"
    assert r.xlen(queue.DIARIZE_STREAM) == 1


def test_submit_returns_none_when_unconfigured(r, monkeypatch):
    monkeypatch.setattr(diarize_jobs.settings, "audio_fetch_url", "")
    monkeypatch.setattr(diarize_jobs.settings, "diarize_result_callback_url", "")
    assert diarize_jobs.submit_diarize_job(session_id="s1", native_meeting_id="m", workspace_id="ws",
                                           client=r) is None


# ── result callback reconciles + is idempotent ──────────────────────────────

def _enqueue_diarize_job(r, *, authoritative="1"):
    payload = {"session_id": "s1", "meeting_id": "meet1", "workspace": "ws1",
               "audio_ref": "u", "callback_url": "u", "authoritative": authoritative}
    return queue.submit(queue.DIARIZE_STREAM, "diarize", payload, client=r)


@pytest.mark.asyncio
async def test_result_authoritative_overwrites_raw(wiring, r):
    import api.diarize_result_routes as dr
    calls, _ = wiring
    job_id = _enqueue_diarize_job(r, authoritative="1")
    segs = [{"start": 0.0, "end": 4.0, "local_speaker": "speaker0"},
            {"start": 4.0, "end": 8.0, "local_speaker": "speaker1"}]
    status = await dr._reconcile_result(job_id, segs, None, client=r)

    assert status == "reconciled"
    assert calls["identify_spans"] == 1
    # AUTHORITATIVE → raw_diarization overwritten, resolved keyed by DiariZen labels + names
    assert calls["set_raw"] is not None and len(calls["set_raw"]) == 3
    assert calls["set_metadata"].resolved_speakers["speaker0"]["voiceprint_id"] == "vp_A"
    assert calls["set_metadata"].resolved_speakers["speaker0"]["name"] == "Alice"
    # enrichment chained AFTER identity
    assert calls["enrich"] == ["s1"]
    assert queue.get_job(job_id, client=r)["reconciled"] == "1"


@pytest.mark.asyncio
async def test_result_authoritative_writes_transcript_when_vfte_empty(wiring, r, monkeypatch):
    """#37: VFTE identify-spans can SUCCEED-but-return-empty (no enrolled/matched voiceprints — the
    common untagged-meeting case). The authoritative DiariZen transcript must STILL be written
    (speakers as labels) instead of leaving the FE stuck on the LIVE preview."""
    import api.diarize_result_routes as dr
    import infra.fpm_consent as fpm
    calls, _ = wiring

    async def empty_identify(ws, audio, spans, *, tag="offline", meeting_id=None, host_user=None):
        calls["identify_spans"] += 1
        return []                      # VFTE found nothing — NO exception
    monkeypatch.setattr(fpm, "identify_spans", empty_identify)

    job_id = _enqueue_diarize_job(r, authoritative="1")
    segs = [{"start": 0.0, "end": 4.0, "local_speaker": "speaker0"},
            {"start": 4.0, "end": 8.0, "local_speaker": "speaker1"}]
    status = await dr._reconcile_result(job_id, segs, None, client=r)

    assert status == "reconciled"
    # THE FIX: empty fpm_segs falls back to the raw diarized segments → transcript IS written.
    assert calls["set_raw"] is not None, "empty VFTE must NOT block the authoritative transcript write"
    assert calls["enrich"] == ["s1"], "enrichment must still chain"


@pytest.mark.asyncio
async def test_result_fallback_branch_does_not_overwrite_raw(wiring, r):
    import api.diarize_result_routes as dr
    calls, _ = wiring
    job_id = _enqueue_diarize_job(r, authoritative="0")
    segs = [{"start": 0.0, "end": 4.0, "local_speaker": "speaker0"}]
    status = await dr._reconcile_result(job_id, segs, None, client=r)

    assert status == "reconciled"
    assert calls["set_raw"] is None, "diart-fallback must NOT overwrite the live transcript"
    assert calls["set_metadata"].resolved_speakers["speaker0"]["voiceprint_id"] == "vp_A"


@pytest.mark.asyncio
async def test_result_is_idempotent(wiring, r):
    import api.diarize_result_routes as dr
    calls, _ = wiring
    job_id = _enqueue_diarize_job(r, authoritative="1")
    segs = [{"start": 0.0, "end": 4.0, "local_speaker": "speaker0"}]

    first = await dr._reconcile_result(job_id, segs, None, client=r)
    second = await dr._reconcile_result(job_id, segs, None, client=r)

    assert first == "reconciled" and second == "duplicate"
    assert calls["identify_spans"] == 1, "redelivered result must NOT re-run identify-spans"
    assert calls["enrich"] == ["s1"], "redelivered result must NOT re-enqueue enrichment"


@pytest.mark.asyncio
async def test_result_unknown_job_ignored(wiring, r):
    import api.diarize_result_routes as dr
    status = await dr._reconcile_result("nope", [], None, client=r)
    assert status == "unknown"


# ── identify_meeting submits (no blocking diarize call) in queue mode ────────

@pytest.mark.asyncio
async def test_identify_meeting_submits_not_blocks_in_queue_mode(r, monkeypatch):
    """Queue mode: identify_meeting must SUBMIT a job and return True (deferred), WITHOUT calling the
    blocking DiariZen client or VFTE identify-spans inline."""
    import connectors.capture.identify as idmod
    from config import settings
    from connectors.capture import diarize_client
    import infra.fpm_consent as fpm

    blocking = {"diarize_recording": 0, "identify_spans": 0}

    async def boom_recording(*a, **k):
        blocking["diarize_recording"] += 1
        return []

    async def boom_identify(*a, **k):
        blocking["identify_spans"] += 1
        return []

    monkeypatch.setattr(diarize_client, "diarize_recording", boom_recording)
    monkeypatch.setattr(fpm, "identify_spans", boom_identify)
    monkeypatch.setattr(settings, "inperson_via_capture", True)
    monkeypatch.setattr(settings, "diarize_jobs", "queue")
    monkeypatch.setattr(diarize_jobs.settings, "audio_fetch_url", "http://c/api/diarize/audio")
    monkeypatch.setattr(diarize_jobs.settings, "diarize_result_callback_url", "http://c/api/diarize/result")
    # the submit grabs its own client via get_client(); point it at fakeredis
    monkeypatch.setattr(queue, "get_client", lambda: r)

    deferred = await idmod.identify_meeting("s1", "meet1", "ws1")

    assert deferred is True, "queue mode must defer identity to the job callback"
    assert blocking == {"diarize_recording": 0, "identify_spans": 0}, "must NOT run identity inline"
    assert r.xlen(queue.DIARIZE_STREAM) == 1, "a diarize job must be enqueued"


@pytest.mark.asyncio
async def test_identify_meeting_falls_back_to_blocking_when_unconfigured(r, monkeypatch):
    """Queue mode but no audio_fetch_url/callback → submit returns None → identify runs inline
    (never lose a finalize). identify_meeting returns False (not deferred)."""
    import connectors.capture.identify as idmod
    from config import settings
    import infra.fpm_consent as fpm

    monkeypatch.setattr(settings, "inperson_via_capture", True)
    monkeypatch.setattr(settings, "diarize_jobs", "queue")
    monkeypatch.setattr(settings, "diarize_url", "")
    monkeypatch.setattr(diarize_jobs.settings, "audio_fetch_url", "")   # unconfigured → can't queue
    monkeypatch.setattr(diarize_jobs.settings, "diarize_result_callback_url", "")
    monkeypatch.setattr(queue, "get_client", lambda: r)
    monkeypatch.setattr(idmod, "_assemble_audio", lambda nid: b"")  # no audio → inline path no-ops

    deferred = await idmod.identify_meeting("s1", "meet1", "ws1")
    assert deferred is False
    assert r.xlen(queue.DIARIZE_STREAM) == 0
