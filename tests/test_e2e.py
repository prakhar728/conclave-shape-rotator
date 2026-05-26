"""
E2E tests for the full Conclave API workflow.

Validates API plumbing — token auth, role enforcement, auto-trigger logic,
and result routing. LLM calls are mocked: no API keys or credits needed.
This is the CI test suite.

Workflow covered:
    1. Instance setup → tokens issued
    2. Participant submits below threshold → received_pending
    3. Nth submission auto-triggers pipeline → received_analysis_complete
    4. Operator manual trigger → runs pipeline
    5. Role-based result views (admin sees all, user sees own)
    6. Token enforcement (missing/wrong/wrong-role → 401/403)

Note: /init was removed in the agent-skill pivot. Tests now seed instances
directly via _setup_instance() until typed POST /instances lands in phase 4.
"""
from __future__ import annotations
import os
os.environ.setdefault("CONCLAVE_DB_PATH", ":memory:")
os.environ.setdefault("CONCLAVE_DISABLE_SCHEDULER", "1")

import secrets
import uuid

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

import storage
from core.models import OperatorConfig, SkillResponse
from skills.hackathon_novelty import skill_card


# --- Fakes ---

def _fake_run_skill(inputs, params):
    """Returns a deterministic SkillResponse for any list of HackathonSubmission inputs."""
    return SkillResponse(
        skill="hackathon_novelty",
        results=[
            {
                "submission_id": s.submission_id,
                "novelty_score": 0.7,
                "aligned": True,
                "criteria_scores": {"originality": 7.0, "feasibility": 6.0},
                "status": "analyzed",
                "analysis_depth": "full",
                "duplicate_of": None,
                "track_alignments": {"DeFi": 0.4},
                "best_fit_track": "DeFi",
                "cluster_label": "A",
                "cluster_size": 2,
                "confidence": "high",
                "name_collisions": [],
            }
            for s in inputs
        ],
    )


def _setup_instance(threshold=5):
    """Seed an instance directly in storage. Returns (instance_id, admin_token).

    Replaces the now-deleted /init flow. Phase 4 will introduce typed POST /instances
    and these tests will be updated to call it instead."""
    instance_id = str(uuid.uuid4())
    config = OperatorConfig(
        criteria={"originality": 0.5, "feasibility": 0.5},
        guidelines="",
        instance_id=instance_id,
    )
    storage.create_instance(
        instance_id=instance_id,
        skill_name="hackathon_novelty",
        config=config.model_dump(),
        threshold=threshold,
    )  # kwargs flow through to the JSON `data` column
    admin_token = secrets.token_urlsafe(16)
    storage.create_token(admin_token, instance_id, role="admin")
    return instance_id, admin_token


# --- Fixtures ---

@pytest.fixture(autouse=True)
def clear_stores():
    """Reset all storage tables before each test."""
    storage.reset_all()
    yield


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


# --- Tests ---

def test_full_e2e_workflow(client):
    """Full happy path: seed instance → submit → admin trigger → view results."""
    with patch.object(skill_card, "run", _fake_run_skill):
        instance_id, admin_token = _setup_instance()

        r = client.post("/register", json={"instance_id": instance_id})
        assert r.status_code == 200
        user_token = r.json()["user_token"]

        # Submit 5 times — all just stored, no auto-trigger anymore (scheduler owns triggering)
        for i in range(1, 6):
            r = client.post(
                "/submit",
                json={"submission_id": f"sub_00{i}", "idea_text": f"Idea number {i}"},
                headers={"X-Instance-Token": user_token},
            )
            assert r.status_code == 200
            body = r.json()
            assert body["status"] == "received"
            assert body["submissions_count"] == i

        # No results yet — pipeline hasn't run
        r = client.get("/results/sub_001", headers={"X-Instance-Token": user_token})
        assert r.status_code == 404

        # Admin triggers evaluation manually
        r = client.post("/trigger", headers={"X-Instance-Token": admin_token})
        assert r.status_code == 200
        assert r.json()["status"] == "complete"
        assert r.json()["results_count"] == 5

        # Participant views their own result
        r = client.get("/results/sub_001", headers={"X-Instance-Token": user_token})
        assert r.status_code == 200
        body = r.json()
        assert body["submission_id"] == "sub_001"
        assert "novelty_score" in body
        assert "confidence" in body
        assert "track_alignments" in body
        # Users should NOT see internal/admin fields
        assert "criteria_scores" not in body
        assert "status" not in body

        # Operator views all results
        r = client.get("/results", headers={"X-Instance-Token": admin_token})
        assert r.status_code == 200
        results = r.json()["results"]
        assert len(results) == 5
        assert all("submission_id" in res for res in results)


def test_token_enforcement(client):
    """Token-based auth and role enforcement."""
    instance_id, admin_token = _setup_instance()

    r = client.post("/register", json={"instance_id": instance_id})
    user_token = r.json()["user_token"]

    # No token → 401
    r = client.post("/submit", json={"submission_id": "s1", "idea_text": "idea"})
    assert r.status_code == 401

    # Garbage token → 403
    r = client.post(
        "/submit",
        json={"submission_id": "s1", "idea_text": "idea"},
        headers={"X-Instance-Token": "not-a-real-token"},
    )
    assert r.status_code == 403

    # Participant cannot trigger manually
    r = client.post("/trigger", headers={"X-Instance-Token": user_token})
    assert r.status_code == 403

    # Participant cannot view all results
    r = client.get("/results", headers={"X-Instance-Token": user_token})
    assert r.status_code == 403

    # Operator can submit (allowed by role)
    r = client.post(
        "/submit",
        json={"submission_id": "s1", "idea_text": "operator's idea"},
        headers={"X-Instance-Token": admin_token},
    )
    assert r.status_code == 200


def test_result_not_found_before_pipeline(client):
    """Requesting a result before the pipeline runs returns 404."""
    instance_id, _ = _setup_instance()

    r = client.post("/register", json={"instance_id": instance_id})
    user_token = r.json()["user_token"]

    r = client.get("/results/sub_001", headers={"X-Instance-Token": user_token})
    assert r.status_code == 404


def test_register_unknown_instance_returns_404(client):
    """Registering for a non-existent instance returns 404."""
    r = client.post("/register", json={"instance_id": "does-not-exist"})
    assert r.status_code == 404


def test_generate_token_issues_bearer_compatible_token(client):
    """POST /generate-token returns {token, expires_at} and the token works with Bearer auth."""
    instance_id, _ = _setup_instance()

    r = client.post("/generate-token", json={"instance_id": instance_id})
    assert r.status_code == 200
    body = r.json()
    assert "token" in body
    assert body["expires_at"] is None
    token = body["token"]

    # Token works with Bearer auth on a protected endpoint
    r = client.get("/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["role"] == "user"
    assert r.json()["instance_id"] == instance_id


def test_generate_token_unknown_instance_returns_404(client):
    r = client.post("/generate-token", json={"instance_id": "does-not-exist"})
    assert r.status_code == 404


def test_bearer_and_x_instance_token_both_accepted(client):
    """Either Bearer or X-Instance-Token header resolves a token."""
    instance_id, admin_token = _setup_instance()

    r = client.get("/me", headers={"X-Instance-Token": admin_token})
    assert r.status_code == 200

    r = client.get("/me", headers={"Authorization": f"Bearer {admin_token}"})
    assert r.status_code == 200


def test_no_auth_headers_returns_401(client):
    r = client.get("/me")
    assert r.status_code == 401


def test_invalid_bearer_returns_403(client):
    r = client.get("/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 403


def test_create_instance_typed(client):
    """POST /instances with a valid typed body returns instance_id, admin_token, enclave_url."""
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    r = client.post(
        "/instances",
        json={
            "name": "Frontier 2026",
            "end_date": future,
            "evaluation_frequency": "1d",
            "tracks": [
                {"name": "DeFi", "description_markdown": "Decentralized finance projects"},
                {"name": "AI", "description_markdown": "AI/ML applications"},
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "instance_id" in body
    assert "admin_token" in body
    assert "enclave_url" in body

    # The admin token works
    r = client.get("/me", headers={"Authorization": f"Bearer {body['admin_token']}"})
    assert r.status_code == 200
    assert r.json()["role"] == "admin"


def test_create_instance_rejects_past_end_date(client):
    from datetime import datetime, timedelta, timezone
    past = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = client.post(
        "/instances",
        json={
            "name": "Past Hackathon",
            "end_date": past,
            "evaluation_frequency": "1d",
            "tracks": [{"name": "X", "description_markdown": "x"}],
        },
    )
    assert r.status_code == 422
    assert "end_date" in r.json()["detail"]


def test_create_instance_rejects_bad_frequency(client):
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    r = client.post(
        "/instances",
        json={
            "name": "Test",
            "end_date": future,
            "evaluation_frequency": "1y",  # 'y' not a valid unit
            "tracks": [{"name": "X", "description_markdown": "x"}],
        },
    )
    assert r.status_code == 422


def test_create_instance_requires_at_least_one_track(client):
    from datetime import datetime, timedelta, timezone
    future = (datetime.now(timezone.utc) + timedelta(days=14)).isoformat()
    r = client.post(
        "/instances",
        json={
            "name": "Test",
            "end_date": future,
            "evaluation_frequency": "1d",
            "tracks": [],
        },
    )
    assert r.status_code == 422


def test_submit_via_bearer(client):
    """Full submit + manual-trigger flow works via Bearer auth (the agent-skill path)."""
    with patch.object(skill_card, "run", _fake_run_skill):
        instance_id, admin_token = _setup_instance()

        r = client.post("/generate-token", json={"instance_id": instance_id})
        token = r.json()["token"]

        for i in (1, 2):
            r = client.post(
                "/submit",
                json={"submission_id": f"sub_{i}", "idea_text": f"idea {i}"},
                headers={"Authorization": f"Bearer {token}"},
            )
            assert r.status_code == 200

        # Admin triggers manually
        r = client.post("/trigger", headers={"Authorization": f"Bearer {admin_token}"})
        assert r.status_code == 200

        # Result accessible via Bearer
        r = client.get("/results/sub_1", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 200
        assert "novelty_score" in r.json()


def test_health_endpoint(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "instances" in body
    assert "hackathon_novelty" in body["skills"]


def test_skills_metadata_endpoints(client):
    # List all skills
    r = client.get("/skills")
    assert r.status_code == 200
    skills = r.json()["skills"]
    assert any(s["name"] == "hackathon_novelty" for s in skills)

    # Single skill
    r = client.get("/skills/hackathon_novelty")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "hackathon_novelty"
    assert "input_schema" in body
    assert "trigger_modes" in body
    assert "roles" in body

    # Non-existent skill
    r = client.get("/skills/nonexistent_skill")
    assert r.status_code == 404


def test_missing_agent_result_produces_error_status():
    """When agent output is missing a submission_id, that result gets status='error'."""
    import numpy as np
    from skills.hackathon_novelty import run_skill
    from skills.hackathon_novelty.models import HackathonSubmission

    inputs = [
        HackathonSubmission(submission_id=f"sub_{i:03d}", idea_text=f"Unique idea number {i}")
        for i in range(1, 6)
    ]
    params = OperatorConfig(criteria={"originality": 0.5, "feasibility": 0.5})

    # Agent returns results for sub_001 through sub_004 only — sub_005 is missing
    partial_results = [
        {
            "submission_id": f"sub_{i:03d}",
            "criteria_scores": {"originality": 7.0, "feasibility": 6.0},
            "status": "analyzed",
            "analysis_depth": "full",
        }
        for i in range(1, 5)
    ]

    det_output = {
        "embeddings": np.zeros((5, 768)),
        "sim_matrix": np.eye(5),
        "novelty_scores": np.array([0.5, 0.6, 0.7, 0.8, 0.9]),
        "percentiles": np.array([20.0, 40.0, 60.0, 80.0, 100.0]),
        "clusters": ["A", "A", "B", "B", "C"],
        "cluster_sizes": [2, 2, 2, 2, 1],
        "submission_ids": [f"sub_{i:03d}" for i in range(1, 6)],
        "name_collisions": {f"sub_{i:03d}": [] for i in range(1, 6)},
        "track_alignments": [{} for _ in range(5)],
        "best_fit_tracks": [None] * 5,
    }

    with patch("skills.hackathon_novelty.run_ingest", return_value={}), \
         patch("skills.hackathon_novelty.run_deterministic", return_value=det_output), \
         patch("skills.hackathon_novelty.run_agent", return_value=partial_results):
        response = run_skill(inputs, params)

    by_id = {r["submission_id"]: r for r in response.results}
    assert by_id["sub_005"]["status"] == "error"
    for i in range(1, 5):
        assert by_id[f"sub_{i:03d}"]["status"] == "analyzed"


def test_manual_retrigger_after_more_submissions(client):
    """Two trigger calls produce results that include later submissions."""
    with patch.object(skill_card, "run", _fake_run_skill):
        instance_id, admin_token = _setup_instance()

        r = client.post("/register", json={"instance_id": instance_id})
        user_token = r.json()["user_token"]

        for i in range(1, 6):
            client.post(
                "/submit",
                json={"submission_id": f"sub_{i:03d}", "idea_text": f"Idea {i}"},
                headers={"X-Instance-Token": user_token},
            )

        # First trigger covers 5 submissions
        r = client.post("/trigger", headers={"X-Instance-Token": admin_token})
        assert r.json()["results_count"] == 5

        # 6th submission lands; second trigger covers all 6
        client.post(
            "/submit",
            json={"submission_id": "sub_006", "idea_text": "Sixth idea"},
            headers={"X-Instance-Token": user_token},
        )
        r = client.post("/trigger", headers={"X-Instance-Token": admin_token})
        assert r.status_code == 200
        assert r.json()["results_count"] == 6

        r = client.get("/results", headers={"X-Instance-Token": admin_token})
        assert len(r.json()["results"]) == 6


def test_submit_missing_required_field_returns_422(client):
    """Submitting without the required idea_text field returns 422."""
    instance_id, _ = _setup_instance()

    r = client.post("/register", json={"instance_id": instance_id})
    user_token = r.json()["user_token"]

    r = client.post(
        "/submit",
        json={"submission_id": "sub_001"},  # missing required idea_text
        headers={"X-Instance-Token": user_token},
    )
    assert r.status_code == 422


def test_cohort_aggregates_admin_only(client):
    """GET /cohort/aggregates returns cluster + track distribution, collisions, cohort size."""
    with patch.object(skill_card, "run", _fake_run_skill):
        instance_id, admin_token = _setup_instance()

        user_token = client.post("/register", json={"instance_id": instance_id}).json()["user_token"]
        for i in range(1, 4):
            client.post(
                "/submit",
                json={"submission_id": f"sub_{i}", "idea_text": f"Idea {i}"},
                headers={"X-Instance-Token": user_token},
            )
        client.post("/trigger", headers={"X-Instance-Token": admin_token})

        # Admin can read aggregates
        r = client.get("/cohort/aggregates", headers={"X-Instance-Token": admin_token})
        assert r.status_code == 200
        body = r.json()
        assert body["cohort_size"] == 3
        assert body["last_evaluation_at"] is not None
        assert isinstance(body["cluster_distribution"], list)
        assert isinstance(body["track_distribution"], list)
        assert "name_collision_pairs" in body

        # User cannot
        r = client.get("/cohort/aggregates", headers={"X-Instance-Token": user_token})
        assert r.status_code == 403


def test_cohort_timeline_records_each_trigger(client):
    """Each /trigger appends to /cohort/timeline."""
    with patch.object(skill_card, "run", _fake_run_skill):
        instance_id, admin_token = _setup_instance()
        user_token = client.post("/register", json={"instance_id": instance_id}).json()["user_token"]

        client.post(
            "/submit",
            json={"submission_id": "sub_1", "idea_text": "first"},
            headers={"X-Instance-Token": user_token},
        )
        client.post("/trigger", headers={"X-Instance-Token": admin_token})

        client.post(
            "/submit",
            json={"submission_id": "sub_2", "idea_text": "second"},
            headers={"X-Instance-Token": user_token},
        )
        client.post("/trigger", headers={"X-Instance-Token": admin_token})

        r = client.get("/cohort/timeline", headers={"X-Instance-Token": admin_token})
        assert r.status_code == 200
        runs = r.json()["runs"]
        assert len(runs) == 2
        assert runs[0]["submission_count"] == 1
        assert runs[1]["submission_count"] == 2


def test_submissions_includes_idea_title(client):
    """Admin sees a sanitized idea_title_or_summary on each submission row."""
    instance_id, admin_token = _setup_instance()
    user_token = client.post("/register", json={"instance_id": instance_id}).json()["user_token"]

    client.post(
        "/submit",
        json={"submission_id": "sub_1", "idea_text": "Decentralized prediction market"},
        headers={"X-Instance-Token": user_token},
    )

    r = client.get("/submissions", headers={"X-Instance-Token": admin_token})
    assert r.status_code == 200
    rows = r.json()["submissions"]
    assert len(rows) == 1
    assert rows[0]["idea_title_or_summary"] == "Decentralized prediction market"


def test_cross_user_result_isolation(client):
    """User A cannot read User B's result even if they know the submission_id."""
    with patch.object(skill_card, "run", _fake_run_skill):
        instance_id, admin_token = _setup_instance()

        # Two distinct users register
        token_a = client.post("/register", json={"instance_id": instance_id}).json()["user_token"]
        token_b = client.post("/register", json={"instance_id": instance_id}).json()["user_token"]

        for i in range(1, 5):
            client.post(
                "/submit",
                json={"submission_id": f"sub_00{i}", "idea_text": f"Idea {i}"},
                headers={"X-Instance-Token": token_a},
            )
        client.post(
            "/submit",
            json={"submission_id": "sub_005", "idea_text": "User B's idea"},
            headers={"X-Instance-Token": token_b},
        )

        client.post("/trigger", headers={"X-Instance-Token": admin_token})

        # User B can read their own result
        r = client.get("/results/sub_005", headers={"X-Instance-Token": token_b})
        assert r.status_code == 200

        # User B cannot read User A's result even knowing the submission_id
        r = client.get("/results/sub_001", headers={"X-Instance-Token": token_b})
        assert r.status_code == 403

        # User A cannot read User B's result
        r = client.get("/results/sub_005", headers={"X-Instance-Token": token_a})
        assert r.status_code == 403
