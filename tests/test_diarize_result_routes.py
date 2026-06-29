"""Task #16 — HTTP wiring for the diarize job-queue routes (audio fetch + result callback).

TestClient-level: service-token gating on the worker audio endpoint, and the result callback
reconciling end-to-end through FastAPI with fakeredis behind get_client(). The reconcile internals
are unit-tested in test_diarize_jobs; here we just prove the routes are mounted + auth + idempotency
flow through the HTTP layer.
"""
import fakeredis
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(monkeypatch):
    import api.diarize_result_routes as dr
    from connectors.jobs import queue
    fake = fakeredis.FakeStrictRedis(decode_responses=True)
    monkeypatch.setattr(queue, "get_client", lambda: fake)
    import main
    return TestClient(main.app), fake, dr


def test_audio_fetch_requires_token_when_configured(client, monkeypatch):
    tc, _fake, dr = client
    monkeypatch.setattr(dr.settings, "audio_fetch_token", "secret")
    r = tc.get("/api/diarize/audio/meet1")
    assert r.status_code == 401
    r = tc.get("/api/diarize/audio/meet1", headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_audio_fetch_serves_assembled_audio(client, monkeypatch):
    tc, _fake, dr = client
    monkeypatch.setattr(dr.settings, "audio_fetch_token", "secret")
    monkeypatch.setattr("connectors.capture.identify._assemble_audio", lambda nid: b"RIFFaudio")
    r = tc.get("/api/diarize/audio/meet1", headers={"Authorization": "Bearer secret"})
    assert r.status_code == 200
    assert r.content == b"RIFFaudio"
    assert r.headers["content-type"] == "audio/wav"


def test_audio_fetch_404_when_no_audio(client, monkeypatch):
    tc, _fake, dr = client
    monkeypatch.setattr(dr.settings, "audio_fetch_token", "")  # open in dev
    monkeypatch.setattr("connectors.capture.identify._assemble_audio", lambda nid: b"")
    r = tc.get("/api/diarize/audio/meet1")
    assert r.status_code == 404


def test_result_route_unknown_job(client, monkeypatch):
    tc, _fake, dr = client
    monkeypatch.setattr(dr.settings, "diarize_result_token", "")
    r = tc.post("/api/diarize/result", json={"job_id": "nope", "segments": []})
    assert r.status_code == 200
    assert r.json()["status"] == "unknown"


def test_result_route_token_gated(client, monkeypatch):
    tc, _fake, dr = client
    monkeypatch.setattr(dr.settings, "diarize_result_token", "secret")
    r = tc.post("/api/diarize/result", json={"job_id": "x", "segments": []})
    assert r.status_code == 401


def test_jobs_status_route(client):
    tc, fake, _dr = client
    from connectors.jobs import queue
    job_id = queue.submit(queue.DIARIZE_STREAM, "diarize", {"session_id": "s1"}, client=fake)
    r = tc.get(f"/api/diarize/jobs/{job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "queued" and body["type"] == "diarize"
    r = tc.get("/api/diarize/jobs/missing")
    assert r.status_code == 404


# ── Option A: HTTP-fronted claim / heartbeat / ack-on-result ────────────────────────────────────

def test_claim_returns_204_when_empty(client, monkeypatch):
    tc, _fake, dr = client
    monkeypatch.setattr(dr.settings, "diarize_result_token", "")
    r = tc.post("/api/diarize/jobs/claim", json={})
    assert r.status_code == 204


def test_claim_token_gated(client, monkeypatch):
    tc, _fake, dr = client
    monkeypatch.setattr(dr.settings, "diarize_result_token", "secret")
    r = tc.post("/api/diarize/jobs/claim", json={})
    assert r.status_code == 401
    r = tc.post("/api/diarize/jobs/claim", json={}, headers={"Authorization": "Bearer wrong"})
    assert r.status_code == 401


def test_claim_hands_out_job_and_marks_processing(client, monkeypatch):
    tc, fake, dr = client
    monkeypatch.setattr(dr.settings, "diarize_result_token", "")
    from connectors.jobs import queue
    job_id = queue.submit(queue.DIARIZE_STREAM, "diarize",
                          {"session_id": "s1", "audio_ref": "http://c/audio/m1",
                           "callback_url": "http://c/result"}, client=fake)
    r = tc.post("/api/diarize/jobs/claim", json={"consumer": "gpu-1"})
    assert r.status_code == 200
    body = r.json()
    assert body["job_id"] == job_id and body["msg_id"]
    assert body["payload"]["audio_ref"] == "http://c/audio/m1"
    # job hash now carries processing + the stashed msg_id + consumer (so /result can ack)
    rec = queue.get_job(job_id, client=fake)
    assert rec["status"] == "processing" and rec["msg_id"] == body["msg_id"]
    assert rec["consumer"] == "gpu-1" and rec["attempts"] == "1"
    # nothing else to claim now → 204
    assert tc.post("/api/diarize/jobs/claim", json={}).status_code == 204


def test_claim_dead_letters_past_max_attempts(client, monkeypatch):
    tc, fake, dr = client
    monkeypatch.setattr(dr.settings, "diarize_result_token", "")
    monkeypatch.setenv("CONCLAVE_JOBS_MAX_ATTEMPTS", "1")
    from connectors.jobs import queue
    job_id = queue.submit(queue.DIARIZE_STREAM, "diarize", {"session_id": "s1"}, client=fake)
    # 1st claim is the allowed attempt; it's never acked (worker vanished) → reclaim re-offers it.
    assert tc.post("/api/diarize/jobs/claim", json={}).status_code == 200
    # idle threshold 0 so the stale entry is reclaimable immediately on the next claim.
    monkeypatch.setenv("CONCLAVE_JOBS_RECLAIM_IDLE_MS", "0")
    r = tc.post("/api/diarize/jobs/claim", json={})
    assert r.status_code == 204                       # attempt 2 > cap → dead-lettered, nothing handed out
    assert fake.xlen(f"{queue.DIARIZE_STREAM}:dead") == 1
    assert queue.get_job(job_id, client=fake)["status"] == "failed"
    assert fake.xpending(queue.DIARIZE_STREAM, queue.DIARIZE_GROUP)["pending"] == 0  # acked away


def test_heartbeat_unknown_job_404(client, monkeypatch):
    tc, _fake, dr = client
    monkeypatch.setattr(dr.settings, "diarize_result_token", "")
    assert tc.post("/api/diarize/jobs/nope/heartbeat").status_code == 404


def test_heartbeat_keeps_claimed_job_warm(client, monkeypatch):
    import time as _time
    tc, fake, dr = client
    monkeypatch.setattr(dr.settings, "diarize_result_token", "")
    from connectors.jobs import queue
    queue.submit(queue.DIARIZE_STREAM, "diarize",
                 {"session_id": "s1", "audio_ref": "a", "callback_url": "c"}, client=fake)
    job_id = tc.post("/api/diarize/jobs/claim", json={}).json()["job_id"]

    def _idle_ms() -> int:
        # XPENDING extended → the entry's idle time (ms since last delivery/claim).
        return fake.xpending_range(queue.DIARIZE_STREAM, queue.DIARIZE_GROUP,
                                   min="-", max="+", count=10)[0]["time_since_delivered"]

    _time.sleep(0.06)                       # let the lease age
    assert _idle_ms() >= 40, "precondition: the claim should have aged"
    r = tc.post(f"/api/diarize/jobs/{job_id}/heartbeat")
    assert r.status_code == 200 and r.json()["ok"] is True
    # the heartbeat must RESET the idle clock (lease kept warm) — a no-op touch leaves it aged.
    assert _idle_ms() < 40, "heartbeat must reset the pending entry's idle timer"
    # still pending (not acked) and still owned — a heartbeat must not complete or drop the job.
    assert fake.xpending(queue.DIARIZE_STREAM, queue.DIARIZE_GROUP)["pending"] == 1


@pytest.mark.asyncio
async def test_result_acks_the_stashed_msg(client, monkeypatch):
    """A claimed job (msg_id stashed) gets acked by /result once reconcile completes — remote workers
    have no Redis, so the server owns the ack. Reconcile internals are mocked; we assert the ack."""
    _tc, fake, dr = client
    from connectors.jobs import queue
    job_id = queue.submit(queue.DIARIZE_STREAM, "diarize",
                          {"session_id": "s1", "meeting_id": "m1", "workspace": "ws1"}, client=fake)
    # claim it so msg_id is stashed (simulate the HTTP-claim path)
    consumer = "gpu-1"
    queue.ensure_group(queue.DIARIZE_STREAM, queue.DIARIZE_GROUP, client=fake)
    msg_id, _fields = queue.read_new(queue.DIARIZE_STREAM, queue.DIARIZE_GROUP, consumer,
                                     client=fake, count=1, block_ms=0)[0]
    queue.set_status(job_id, "processing", client=fake, msg_id=msg_id, consumer=consumer)
    assert fake.xpending(queue.DIARIZE_STREAM, queue.DIARIZE_GROUP)["pending"] == 1

    async def _fake_identify(ws, audio, segs, tag=None):
        return segs
    monkeypatch.setattr("connectors.capture.identify._assemble_audio", lambda nid: b"")
    monkeypatch.setattr("transcripts.store.load_session", lambda sid: object())
    monkeypatch.setattr("connectors.capture.reconcile.reconcile_identity",
                        lambda *a, **k: None)
    monkeypatch.setattr("infra.fpm_consent.identify_spans", _fake_identify)
    monkeypatch.setattr("connectors.jobs.enqueue.enrich", lambda sid, client=None: None)

    label = await dr._reconcile_result(job_id, [], None, client=fake)
    assert label == "reconciled"
    assert queue.get_job(job_id, client=fake)["status"] == "done"
    assert fake.xpending(queue.DIARIZE_STREAM, queue.DIARIZE_GROUP)["pending"] == 0  # server acked
