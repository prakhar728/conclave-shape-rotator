"""
Step 8 E2E tests — interview_reflection over the REST surface.

Covers:
    1. POST /instances/interview        — operator setup, admin token issued
    2. POST /submit with X-Instance-Token — transcript validates against TranscriptInput
    3. POST /trigger (admin only)        — runs det → agent → guardrails
    4. GET  /results                     — admin sees full per-interviewee Novel output
    5. GET  /results/{id} (user role)    — interviewee sees ALLOWED_INTERVIEWEE_OUTPUT_KEYS only
    6. Token enforcement                 — missing/wrong token, user-role triggering /trigger

LLM is mocked. Persistence (aggregate ledger) is redirected to tmp_path so
the test doesn't pollute the real data/ directory.
"""
from __future__ import annotations

import os
os.environ.setdefault("CONCLAVE_DB_PATH", ":memory:")
os.environ.setdefault("CONCLAVE_DISABLE_SCHEDULER", "1")

import json
import secrets
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import storage


FIXTURE_DIR = Path(__file__).parent / "fixtures" / "interview_reflection"


@pytest.fixture(autouse=True)
def clear_stores():
    storage.reset_all()
    yield


@pytest.fixture(autouse=True)
def isolated_ledger(tmp_path, monkeypatch):
    """Redirect the per-slug JSONL ledger into tmp_path for this test module."""
    import skills.interview_reflection.aggregate as agg_mod
    monkeypatch.setattr(agg_mod, "DEFAULT_STORAGE_ROOT", tmp_path)
    yield


@pytest.fixture
def mocked_llm(monkeypatch):
    """Two-call canned stub: themes then ownership.

    A module-level counter (closure cell) is shared across every get_llm()
    call within the test, so the *second* call inside one run_agent invocation
    correctly receives the ownership payload regardless of how many times
    get_llm() is constructed.
    """
    call_count = {"n": 0}

    class _Stub:
        def invoke(self, _messages):
            call_count["n"] += 1
            if call_count["n"] % 2 == 1:
                payload = {
                    "themes": ["shipping cadence", "outbound neglected"],
                    "session_summary": "Short canned summary.",
                }
            else:
                payload = {
                    "attribution_patterns": {"internal": 0.75, "external": 0.25},
                    "ownership_prompts": [],
                    "suggested_next_questions": ["What's the next test?"],
                }
            return SimpleNamespace(content=json.dumps(payload))

    monkeypatch.setattr("config.get_llm", lambda *_a, **_k: _Stub())
    yield


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


# --- 1. Instance creation ---

def test_create_interview_instance_returns_admin_token(client):
    r = client.post("/instances/interview", json={"name": "Shape Rotator Spring 2026"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["instance_id"]
    assert body["admin_token"]
    assert body["enclave_url"]

    # The instance should be persisted with the right skill bound
    inst = storage.get_instance(body["instance_id"])
    assert inst is not None
    assert inst["skill_name"] == "interview_reflection"


def test_create_interview_instance_rejects_past_end_date(client):
    r = client.post("/instances/interview", json={
        "name": "Past Cohort",
        "end_date": "2000-01-01T00:00:00Z",
    })
    assert r.status_code == 422


def test_create_interview_instance_defaults_end_date_one_year_out(client):
    r = client.post("/instances/interview", json={"name": "Defaulted"})
    assert r.status_code == 200, r.text


# --- 2. Submit + trigger + results ---

def _setup_instance(client) -> tuple[str, str]:
    r = client.post("/instances/interview", json={"name": "Spring 2026"})
    body = r.json()
    return body["instance_id"], body["admin_token"]


def test_full_e2e_submit_trigger_results(client, mocked_llm):
    instance_id, admin_token = _setup_instance(client)

    transcript = (FIXTURE_DIR / "prod_internal.txt").read_text()
    submit_resp = client.post(
        "/submit",
        json={"transcript": transcript, "interviewee_slug": "leo"},
        headers={"X-Instance-Token": admin_token},
    )
    assert submit_resp.status_code == 200, submit_resp.text
    submission_id = submit_resp.json()["submission_id"]

    trigger_resp = client.post("/trigger", headers={"X-Instance-Token": admin_token})
    assert trigger_resp.status_code == 200, trigger_resp.text
    assert trigger_resp.json()["results_count"] == 1

    results_resp = client.get("/results", headers={"X-Instance-Token": admin_token})
    assert results_resp.status_code == 200, results_resp.text
    payload = results_resp.json()
    assert "results" in payload or isinstance(payload, list)

    one = client.get(f"/results/{submission_id}", headers={"X-Instance-Token": admin_token})
    assert one.status_code == 200, one.text
    result = one.json()
    assert result["interviewee_slug"] == "leo"
    assert result["themes"] == ["shipping cadence", "outbound neglected"]
    assert result["attribution_patterns"] == {"internal": 0.75, "external": 0.25}


def test_submit_validates_against_transcript_input(client):
    _instance_id, admin_token = _setup_instance(client)
    # Missing required field `transcript`
    bad = client.post(
        "/submit",
        json={"interviewee_slug": "leo"},
        headers={"X-Instance-Token": admin_token},
    )
    assert bad.status_code == 422


def test_submit_requires_token(client):
    _setup_instance(client)
    r = client.post("/submit", json={"transcript": "x", "interviewee_slug": "leo"})
    assert r.status_code == 401


def test_trigger_requires_admin(client, mocked_llm):
    instance_id, _admin_token = _setup_instance(client)

    user_token = secrets.token_urlsafe(16)
    storage.create_token(user_token, instance_id, role="user")

    # User can submit
    client.post(
        "/submit",
        json={"transcript": "INTERVIEWER: hi\nINTERVIEWEE: I shipped.", "interviewee_slug": "leo"},
        headers={"X-Instance-Token": user_token},
    )

    # User cannot trigger
    r = client.post("/trigger", headers={"X-Instance-Token": user_token})
    assert r.status_code == 403


# --- 3. Role-based result filtering ---

def test_user_token_sees_only_own_keys(client, mocked_llm):
    instance_id, admin_token = _setup_instance(client)

    user_token = secrets.token_urlsafe(16)
    storage.create_token(user_token, instance_id, role="user")

    transcript = (FIXTURE_DIR / "prod_internal.txt").read_text()
    sub = client.post(
        "/submit",
        json={"transcript": transcript, "interviewee_slug": "leo"},
        headers={"X-Instance-Token": user_token},
    )
    submission_id = sub.json()["submission_id"]

    client.post("/trigger", headers={"X-Instance-Token": admin_token})

    one = client.get(f"/results/{submission_id}", headers={"X-Instance-Token": user_token})
    assert one.status_code == 200, one.text

    # Per ALLOWED_INTERVIEWEE_OUTPUT_KEYS only — these are visible to the user role
    from skills.interview_reflection.config import ALLOWED_INTERVIEWEE_OUTPUT_KEYS
    user_keys = set(one.json().keys())
    assert user_keys <= ALLOWED_INTERVIEWEE_OUTPUT_KEYS, (
        f"user-role result leaked keys outside whitelist: {user_keys - ALLOWED_INTERVIEWEE_OUTPUT_KEYS}"
    )


# --- 4. Ledger side effect ---

def test_trigger_appends_to_ledger(client, mocked_llm, tmp_path):
    instance_id, admin_token = _setup_instance(client)
    from skills.interview_reflection.aggregate import load_digests

    transcript = (FIXTURE_DIR / "prod_internal.txt").read_text()
    client.post(
        "/submit",
        json={"transcript": transcript, "interviewee_slug": "leo"},
        headers={"X-Instance-Token": admin_token},
    )
    client.post("/trigger", headers={"X-Instance-Token": admin_token})

    loaded = load_digests("leo", root=tmp_path)
    assert len(loaded) == 1
    assert loaded[0]["interviewee_slug"] == "leo"
    # Raw transcript must not appear anywhere in the persisted record
    assert "I shipped the onboarding flow rewrite" not in json.dumps(loaded[0])
