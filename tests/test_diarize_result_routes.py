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
