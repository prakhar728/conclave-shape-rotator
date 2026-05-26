"""
Step 1 scaffold test — confirms interview_reflection is routable via /skills.

This is the only test for this skill in Step 1. Later build_pipeline.md steps add
tests against fixtures, layer outputs, guardrails, and aggregation.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_interview_reflection_skill_metadata(client):
    # Listed in /skills
    r = client.get("/skills")
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["skills"]]
    assert "interview_reflection" in names

    # Resolvable by name with full metadata shape
    r = client.get("/skills/interview_reflection")
    assert r.status_code == 200
    body = r.json()
    assert body["name"] == "interview_reflection"
    assert "input_schema" in body
    assert "trigger_modes" in body
    assert "roles" in body
    assert "admin" in body["roles"]
