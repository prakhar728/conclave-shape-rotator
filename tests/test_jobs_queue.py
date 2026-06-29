"""Task #16 — durable job-queue core on fakeredis (GPU-independent).

Covers the queue substrate (`connectors/jobs/queue.py`) + the Conclave worker dispatch
(`connectors/jobs/worker.py`): full lifecycle (submit → claim → complete → ack), retry on a
handler exception (job stays pending, then a reclaim re-runs it), dead-letter after N attempts,
and the DURABILITY proof (kill a worker mid-job → another reclaims the pending entry → completes,
no job lost). No event loop, no real Redis, no LLM/DB — fakeredis + a stub handler.
"""
import fakeredis
import pytest

from connectors.jobs import queue, worker

STREAM = "test_jobs"
GROUP = "test-workers"


@pytest.fixture
def r():
    client = fakeredis.FakeStrictRedis(decode_responses=True)
    queue.ensure_group(STREAM, GROUP, client=client)
    return client


def test_submit_writes_hash_and_stream(r):
    job_id = queue.submit(STREAM, "enrich", {"session_id": "s1"}, client=r)
    job = queue.get_job(job_id, client=r)
    assert job["status"] == "queued"
    assert job["type"] == "enrich"
    assert job["attempts"] == "0"
    assert job["payload_obj"] == {"session_id": "s1"}
    # the stream carries exactly one entry
    assert r.xlen(STREAM) == 1


def test_full_lifecycle_submit_claim_complete_ack(r, monkeypatch):
    ran = []
    monkeypatch.setattr(worker, "_handler_for", lambda t: (lambda sid: ran.append(sid)))
    job_id = queue.submit(STREAM, "enrich", {"session_id": "s1"}, client=r)

    msgs = queue.read_new(STREAM, GROUP, "w1", client=r)
    assert len(msgs) == 1
    msg_id, fields = msgs[0]
    result = worker.process_message(fields, client=r, stream=STREAM, group=GROUP, msg_id=msg_id)

    assert result == "done"
    assert ran == ["s1"]
    assert queue.get_job(job_id, client=r)["status"] == "done"
    # ACKed → no pending entries remain
    pending = r.xpending(STREAM, GROUP)
    assert pending["pending"] == 0


def test_handler_exception_leaves_job_pending(r, monkeypatch):
    def boom(sid):
        raise RuntimeError("handler failed")
    monkeypatch.setattr(worker, "_handler_for", lambda t: boom)
    job_id = queue.submit(STREAM, "enrich", {"session_id": "s1"}, client=r)

    msg_id, fields = queue.read_new(STREAM, GROUP, "w1", client=r)[0]
    with pytest.raises(RuntimeError):
        worker.process_message(fields, client=r, stream=STREAM, group=GROUP, msg_id=msg_id)

    # NOT acked → still pending, so a reclaim can retry it (no lost job).
    assert r.xpending(STREAM, GROUP)["pending"] == 1
    assert queue.get_job(job_id, client=r)["status"] == "processing"


def test_durability_killed_worker_job_reclaimed_and_completes(r, monkeypatch):
    """Worker A claims a job then dies (never acks). Worker B reclaims the stale pending entry
    and completes it. The job is processed exactly once-to-success and is never lost."""
    ran = []
    monkeypatch.setattr(worker, "_handler_for", lambda t: (lambda sid: ran.append(sid)))
    job_id = queue.submit(STREAM, "enrich", {"session_id": "s1"}, client=r)

    # Worker A claims it but "crashes" before processing (simulate: read, then do nothing/ack-less).
    a_msg_id, _a_fields = queue.read_new(STREAM, GROUP, "workerA", client=r)[0]
    assert r.xpending(STREAM, GROUP)["pending"] == 1  # owned by A, un-acked

    # Worker B reclaims entries idle >= 0ms (min_idle_ms=0 for the test) and runs them.
    reclaimed = queue.reclaim_stale(STREAM, GROUP, "workerB", client=r, min_idle_ms=0)
    assert [m[0] for m in reclaimed] == [a_msg_id]  # same entry, now owned by B
    b_msg_id, b_fields = reclaimed[0]
    worker.process_message(b_fields, client=r, stream=STREAM, group=GROUP, msg_id=b_msg_id)

    assert ran == ["s1"]                              # ran exactly once, by B
    assert queue.get_job(job_id, client=r)["status"] == "done"
    assert r.xpending(STREAM, GROUP)["pending"] == 0  # nothing left pending → not lost


def test_dead_letter_after_max_attempts(r, monkeypatch):
    monkeypatch.setenv("CONCLAVE_JOBS_MAX_ATTEMPTS", "2")

    def boom(sid):
        raise RuntimeError("always fails")
    monkeypatch.setattr(worker, "_handler_for", lambda t: boom)
    job_id = queue.submit(STREAM, "enrich", {"session_id": "s1"}, client=r)

    msg_id, fields = queue.read_new(STREAM, GROUP, "w1", client=r)[0]
    # attempt 1 + 2 fail (raise, stay pending); attempt 3 trips the cap → dead-letter.
    for _ in range(2):
        with pytest.raises(RuntimeError):
            worker.process_message(fields, client=r, stream=STREAM, group=GROUP, msg_id=msg_id)
    result = worker.process_message(fields, client=r, stream=STREAM, group=GROUP, msg_id=msg_id)

    assert result == "failed"
    assert queue.get_job(job_id, client=r)["status"] == "failed"
    assert r.xlen(f"{STREAM}:dead") == 1                 # moved to dead-letter
    assert r.xpending(STREAM, GROUP)["pending"] == 0     # acked away → stops cycling


def test_unknown_job_type_is_skipped_and_acked(r):
    job_id = queue.submit(STREAM, "bogus-type", {"session_id": "s1"}, client=r)
    msg_id, fields = queue.read_new(STREAM, GROUP, "w1", client=r)[0]
    result = worker.process_message(fields, client=r, stream=STREAM, group=GROUP, msg_id=msg_id)
    assert result == "skipped"
    assert r.xpending(STREAM, GROUP)["pending"] == 0
    assert queue.get_job(job_id, client=r)["status"] == "done"
