"""Tests for the Solana attestation path.

By default (no CONCLAVE_SOLANA_KEYPAIR set), publish_attestation runs in
local-only mode and skips the network call. These tests cover that path
plus the API endpoints and storage. The actual devnet broadcast is
exercised manually during the smoke test in phase 9.
"""
from __future__ import annotations
import os
os.environ.setdefault("CONCLAVE_DB_PATH", ":memory:")
os.environ.setdefault("CONCLAVE_DISABLE_SCHEDULER", "1")

import pytest
from fastapi.testclient import TestClient

import storage
from infra import solana
from tests.test_e2e import _setup_instance, _fake_run_skill  # noqa: F401
from unittest.mock import patch
from skills.hackathon_novelty import skill_card


@pytest.fixture(autouse=True)
def clear_stores():
    storage.reset_all()
    yield


@pytest.fixture
def client():
    from main import app
    return TestClient(app)


def test_hash_report_is_deterministic():
    a = [{"submission_id": "x", "novelty_score": 0.5}, {"submission_id": "y", "novelty_score": 0.3}]
    b = list(reversed(a))  # same content, different order
    assert solana.hash_report(a) == solana.hash_report(b)


def test_hash_report_changes_with_payload():
    a = [{"submission_id": "x", "novelty_score": 0.5}]
    b = [{"submission_id": "x", "novelty_score": 0.6}]
    assert solana.hash_report(a) != solana.hash_report(b)


def test_publish_attestation_local_only_when_unconfigured(monkeypatch):
    monkeypatch.delenv("CONCLAVE_SOLANA_KEYPAIR", raising=False)
    record = solana.publish_attestation(b"\x00" * 32)
    assert record["status"] == "local_only"
    assert record["tx_sig"] is None
    assert record["report_hash_hex"] == "00" * 32


def test_publish_endpoint_records_attestation(client):
    """Admin-only POST /attestations/publish records an attestation row even in local_only mode."""
    with patch.object(skill_card, "run", _fake_run_skill):
        instance_id, admin_token = _setup_instance()
        user_token = client.post("/register", json={"instance_id": instance_id}).json()["user_token"]
        client.post(
            "/submit",
            json={"submission_id": "sub_1", "idea_text": "An idea"},
            headers={"X-Instance-Token": user_token},
        )
        client.post("/trigger", headers={"X-Instance-Token": admin_token})

        r = client.post("/attestations/publish", headers={"X-Instance-Token": admin_token})
        assert r.status_code == 200
        latest = r.json()["latest"]
        assert latest is not None
        assert latest["status"] == "local_only"
        assert latest["report_hash"]

        # Listed via GET /attestations
        r = client.get("/attestations", headers={"X-Instance-Token": admin_token})
        assert r.status_code == 200
        att = r.json()["attestations"]
        assert len(att) == 1


def test_publish_endpoint_admin_only(client):
    instance_id, _ = _setup_instance()
    user_token = client.post("/register", json={"instance_id": instance_id}).json()["user_token"]
    r = client.post("/attestations/publish", headers={"X-Instance-Token": user_token})
    assert r.status_code == 403
