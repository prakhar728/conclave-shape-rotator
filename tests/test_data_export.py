"""Task #18 — "download my data" export.

Covers the §7 verification sketch + the load-bearing scope isolation:
  - owner scope: A's export = only A's owned meetings; B's data ABSENT.
  - manifest round-trip: every owned session id + its transcript text present.
  - shares reflect #31's ShareConfig flags (transcript/insights/audio).
  - KB entities/obligations included; embeddings/chunks excluded.
  - voiceprints = refs only + a pointer to #4's export endpoint.
  - audio-ON rides the #16 queue (async), and the job produces audio.wav.
  - async export is owner-scoped (B can't read/download A's export).
"""
from __future__ import annotations

import io
import json
import os
import tempfile
import zipfile

import pytest
from fastapi.testclient import TestClient


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _export_env(monkeypatch):
    monkeypatch.setenv("CONCLAVE_EXPORT_DIR", tempfile.mkdtemp(prefix="export-test-"))
    monkeypatch.setenv("CONCLAVE_AUDIO_DIR", tempfile.mkdtemp(prefix="export-audio-"))
    monkeypatch.setenv("CONCLAVE_AUDIO_ENC_KEY", "11" * 32)
    from config import settings
    monkeypatch.setattr(settings, "audio_enc_key", "11" * 32, raising=False)
    yield


@pytest.fixture(autouse=True)
def _clean():
    from storage.sqlite import _get_conn
    from tests.conftest import reset_workspace_domain_tables
    conn = _get_conn()
    conn.execute("DELETE FROM transcript_sessions")
    conn.execute("DELETE FROM entity_mentions")
    conn.execute("DELETE FROM entities")
    conn.execute("DELETE FROM obligations")
    reset_workspace_domain_tables()
    yield


@pytest.fixture
def client(monkeypatch) -> TestClient:
    import auth.routes as ar
    monkeypatch.setattr(ar, "supabase_enabled", lambda: True)
    monkeypatch.setattr(ar, "_supabase_send_otp", lambda email: None)
    monkeypatch.setattr(ar, "_supabase_verify_otp", lambda email, token: f"sb-{email}")
    from main import app
    return TestClient(app)


def _login(client: TestClient, email: str) -> dict:
    r = client.post("/auth/v1/verify-otp", json={"email": email, "token": "000000"})
    assert r.status_code == 200, r.text
    return r.json()


def _make_user(email: str) -> tuple[str, str]:
    """Create a user + Personal workspace directly (no login). Returns (uid, ws_id)."""
    from infra import identity, workspaces
    u = identity.upsert_user_by_supabase(f"sb-{email}", email)
    ws = workspaces.ensure_personal_workspace(u["id"])
    return u["id"], ws["id"]


def _seed_session(sid: str, uid: str, ws_id: str, *, text: str = "hello world",
                  resolved_speakers: dict | None = None, store_audio: bool | None = None):
    from transcripts import store
    from transcripts.models import Derived, RawSegment, Session, SessionMetadata
    md = SessionMetadata(date="2026-06-29", source="capture")
    if resolved_speakers is not None:
        md.resolved_speakers = resolved_speakers
    if store_audio is not None:
        md.store_audio = store_audio
    sess = Session(
        session_id=sid,
        raw_diarization=[RawSegment(speaker="A", text=text, start=0.0, end=1.0)],
        metadata=md,
        derived=Derived(summary=f"summary of {sid}"),
    )
    store.save_session(sess)
    store.set_workspace(sid, ws_id, uid, visibility="workspace")


def _zip_from(resp) -> zipfile.ZipFile:
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/zip")
    return zipfile.ZipFile(io.BytesIO(resp.content))


# --------------------------------------------------------------------------- #
# 1. Scope isolation — the load-bearing assertion
# --------------------------------------------------------------------------- #
class TestScopeIsolation:
    def test_export_contains_only_owner_meetings(self, client):
        me = _login(client, "alice@x.com")
        a_uid, a_ws = me["user"]["id"], me["workspace"]["id"]
        _seed_session("mtg-alice", a_uid, a_ws, text="alice secret")

        # Bob owns a different meeting in his own workspace.
        b_uid, b_ws = _make_user("bob@x.com")
        _seed_session("mtg-bob", b_uid, b_ws, text="bob secret")

        zf = _zip_from(client.get("/api/users/me/export"))
        names = zf.namelist()
        assert "meetings/mtg-alice/meeting.json" in names
        assert "meetings/mtg-alice/transcript.txt" in names
        # Bob's meeting must be wholly absent — no file, no manifest entry, no text.
        assert not any("mtg-bob" in n for n in names)
        manifest = json.loads(zf.read("manifest.json"))
        sids = {m["session_id"] for m in manifest["meetings"]}
        assert sids == {"mtg-alice"}
        blob = b"".join(zf.read(n) for n in names)
        assert b"bob secret" not in blob
        assert b"alice secret" in blob


# --------------------------------------------------------------------------- #
# 2. Manifest round-trip
# --------------------------------------------------------------------------- #
class TestManifest:
    def test_every_owned_session_in_manifest_with_transcript(self, client):
        me = _login(client, "alice@x.com")
        uid, ws = me["user"]["id"], me["workspace"]["id"]
        for sid in ("m1", "m2", "m3"):
            _seed_session(sid, uid, ws, text=f"words of {sid}")

        zf = _zip_from(client.get("/api/users/me/export"))
        manifest = json.loads(zf.read("manifest.json"))
        assert manifest["schema_version"] == "export-v0"
        assert manifest["counts"]["meetings"] == 3
        assert manifest["user"]["email"] == "alice@x.com"
        for sid in ("m1", "m2", "m3"):
            assert f"meetings/{sid}/meeting.json" in zf.namelist()
            txt = zf.read(f"meetings/{sid}/transcript.txt").decode()
            assert f"words of {sid}" in txt
        # embeddings/chunks explicitly excluded (documented in the manifest)
        assert "embeddings" in manifest["excluded"]


# --------------------------------------------------------------------------- #
# 3. Shares reflect #31 ShareConfig flags
# --------------------------------------------------------------------------- #
class TestShares:
    def test_meeting_json_carries_share_flags(self, client):
        me = _login(client, "alice@x.com")
        uid, ws = me["user"]["id"], me["workspace"]["id"]
        _seed_session("shared-mtg", uid, ws)
        from infra.workspaces import ShareConfig, add_meeting_share
        add_meeting_share(
            "shared-mtg", "bob@x.com", uid,
            config=ShareConfig(transcript=True, insights=False, audio=True),
        )

        zf = _zip_from(client.get("/api/users/me/export"))
        meeting = json.loads(zf.read("meetings/shared-mtg/meeting.json"))
        shares = meeting["shares"]
        assert len(shares) == 1
        s = shares[0]
        assert s["user_email"] == "bob@x.com"
        assert s["share_transcript"] is True
        assert s["share_insights"] is False
        assert s["share_audio"] is True


# --------------------------------------------------------------------------- #
# 4. KB knowledge + voiceprint refs
# --------------------------------------------------------------------------- #
class TestKnowledgeAndVoiceprints:
    def test_kb_entities_included(self, client):
        me = _login(client, "alice@x.com")
        uid, ws = me["user"]["id"], me["workspace"]["id"]
        _seed_session("kb-mtg", uid, ws)
        from storage import kb_graph
        eid = kb_graph.insert_entity("person", "Ada Lovelace", ["Ada"])
        kb_graph.add_mentions(eid, "kb-mtg", [0], "Ada")

        zf = _zip_from(client.get("/api/users/me/export"))
        meeting = json.loads(zf.read("meetings/kb-mtg/meeting.json"))
        names = [e["canonical_name"] for e in meeting["knowledge"]["entities"]]
        assert "Ada Lovelace" in names
        assert "obligations" in meeting["knowledge"]
        assert "facts" in meeting["knowledge"]

    def test_voiceprint_refs_only_plus_pointer(self, client):
        me = _login(client, "alice@x.com")
        uid, ws = me["user"]["id"], me["workspace"]["id"]
        _seed_session(
            "vp-mtg", uid, ws,
            resolved_speakers={"A": {"voiceprint_id": "vp_123", "name": "Ada"}},
        )
        zf = _zip_from(client.get("/api/users/me/export"))
        meeting = json.loads(zf.read("meetings/vp-mtg/meeting.json"))
        assert meeting["voiceprint_refs"] == ["vp_123"]
        manifest = json.loads(zf.read("manifest.json"))
        assert "vp_123" in manifest["voiceprints"]["referenced_ids"]
        assert manifest["voiceprints"]["export_endpoint"] == "/v1/me/voiceprints/export"
        # refs only — the raw vector bytes never travel in the dump
        blob = b"".join(zf.read(n) for n in zf.namelist())
        assert b"exemplars" not in blob


# --------------------------------------------------------------------------- #
# 5. Audio opt-in rides the #16 queue (async); sync path carries no audio
# --------------------------------------------------------------------------- #
class TestAudioQueue:
    def test_start_job_enqueues_data_export(self, client, monkeypatch):
        _login(client, "alice@x.com")
        calls = []
        import connectors.jobs.enqueue as enq
        monkeypatch.setattr(enq, "data_export", lambda export_id: calls.append(export_id))

        r = client.post("/api/users/me/export/jobs", json={"include_audio": True})
        assert r.status_code == 202, r.text
        body = r.json()
        assert body["status"] == "pending"
        assert body["include_audio"] is True
        assert calls == [body["export_id"]]  # the export id was handed to the queue

    def test_enqueue_submits_onto_conclave_stream(self, monkeypatch):
        """When the queue is ON + reachable, data_export lands on conclave_jobs."""
        from config import settings
        from connectors.jobs import enqueue, queue
        monkeypatch.setattr(settings, "jobs_queue", True, raising=False)
        submitted = {}

        class _FakeClient:  # marker — enqueue only checks it's not None
            pass

        monkeypatch.setattr(queue, "get_client", lambda: _FakeClient())

        def _fake_submit(stream, job_type, payload, *, client):
            submitted.update(stream=stream, job_type=job_type, payload=payload)
            return "job-xyz"

        monkeypatch.setattr(queue, "submit", _fake_submit)
        job_id = enqueue.data_export("exp_abc")
        assert job_id == "job-xyz"
        assert submitted["stream"] == queue.CONCLAVE_STREAM
        assert submitted["job_type"] == "data_export"
        assert submitted["payload"] == {"export_id": "exp_abc"}

    def test_worker_builds_zip_with_audio(self, client, monkeypatch):
        """process_message('data_export') decrypts + bundles audio into the ZIP."""
        me = _login(client, "alice@x.com")
        uid, ws = me["user"]["id"], me["workspace"]["id"]
        _seed_session("aud-mtg", uid, ws, store_audio=True)

        # Stub the audio assembly to a known WAV-ish blob (crypto covered elsewhere).
        import infra.data_export as de
        monkeypatch.setattr(de, "_load_audio", lambda sid: b"RIFFfake-wav-" + sid.encode())

        user = {"id": uid, "email": "alice@x.com", "display_name": None}
        export_id = de.create_export(user, include_audio=True)
        from connectors.jobs import worker, queue
        fields = {
            "job_id": None, "type": "data_export",
            "payload": json.dumps({"export_id": export_id}),
        }
        # No real Redis: attempts/ack paths are no-ops when job_id/msg_id are None.
        result = worker.process_message(fields, client=None, msg_id=None)
        assert result == "done"

        status = de.get_export(export_id)
        assert status["status"] == "done"
        zf = zipfile.ZipFile(de.zip_path(export_id))
        assert "meetings/aud-mtg/audio.wav" in zf.namelist()
        assert zf.read("meetings/aud-mtg/audio.wav") == b"RIFFfake-wav-aud-mtg"

    def test_sync_export_never_includes_audio(self, client, monkeypatch):
        me = _login(client, "alice@x.com")
        uid, ws = me["user"]["id"], me["workspace"]["id"]
        _seed_session("aud-mtg", uid, ws, store_audio=True)
        import infra.data_export as de
        monkeypatch.setattr(de, "_load_audio", lambda sid: b"RIFFshould-not-appear")
        zf = _zip_from(client.get("/api/users/me/export"))
        assert not any(n.endswith("audio.wav") for n in zf.namelist())


# --------------------------------------------------------------------------- #
# 6. Async export ownership (scope isolation on the download side)
# --------------------------------------------------------------------------- #
class TestAsyncOwnership:
    def test_other_user_cannot_read_or_download(self, client):
        me = _login(client, "alice@x.com")
        uid = me["user"]["id"]
        import infra.data_export as de
        export_id = de.create_export(
            {"id": uid, "email": "alice@x.com", "display_name": None}, include_audio=False
        )
        # Bob logs in on the same client (cookie now Bob) and probes Alice's export.
        _login(client, "mallory@x.com")
        assert client.get(f"/api/users/me/export/jobs/{export_id}").status_code == 404
        assert client.get(
            f"/api/users/me/export/jobs/{export_id}/download"
        ).status_code == 404

    def test_owner_polls_and_downloads(self, client):
        me = _login(client, "alice@x.com")
        uid, ws = me["user"]["id"], me["workspace"]["id"]
        _seed_session("m1", uid, ws)
        import infra.data_export as de
        user = {"id": uid, "email": "alice@x.com", "display_name": None}
        export_id = de.create_export(user, include_audio=False)

        # Pending → download 409.
        assert client.get(f"/api/users/me/export/jobs/{export_id}").json()["status"] == "pending"
        assert client.get(
            f"/api/users/me/export/jobs/{export_id}/download"
        ).status_code == 409

        de.run_export_job(export_id)
        assert client.get(f"/api/users/me/export/jobs/{export_id}").json()["status"] == "done"
        zf = _zip_from(client.get(f"/api/users/me/export/jobs/{export_id}/download"))
        assert "manifest.json" in zf.namelist()


# --------------------------------------------------------------------------- #
# 7. Auth required
# --------------------------------------------------------------------------- #
class TestAuth:
    def test_anonymous_gets_401(self, client):
        assert client.get("/api/users/me/export").status_code == 401
