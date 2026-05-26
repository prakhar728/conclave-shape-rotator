"""SQLite-backed persistent storage for Conclave.

Replaces the in-memory dicts that previously lived in api/routes.py.
All state survives enclave restart.

Path resolution: env var CONCLAVE_DB_PATH (default ./data/conclave.db).
Tests set CONCLAVE_DB_PATH=:memory: via the storage fixture.
"""
from storage.sqlite import (
    init_db,
    reset_all,
    # instances
    create_instance,
    get_instance,
    has_instance,
    set_instance_triggered,
    list_instances,
    count_instances,
    # submissions
    upsert_submission,
    get_submission,
    list_submissions,
    count_submissions,
    # results
    upsert_result,
    get_result,
    list_results,
    # tokens
    create_token,
    get_token,
    has_token,
    add_submission_to_token,
    # registrations
    get_registration_token,
    set_registration_token,
    # evaluation runs
    record_evaluation_run,
    list_evaluation_runs,
    # attestations
    record_attestation,
    list_attestations,
)

__all__ = [
    "init_db",
    "reset_all",
    "create_instance",
    "get_instance",
    "has_instance",
    "set_instance_triggered",
    "list_instances",
    "count_instances",
    "upsert_submission",
    "get_submission",
    "list_submissions",
    "count_submissions",
    "upsert_result",
    "get_result",
    "list_results",
    "create_token",
    "get_token",
    "has_token",
    "add_submission_to_token",
    "get_registration_token",
    "set_registration_token",
    "record_evaluation_run",
    "list_evaluation_runs",
    "record_attestation",
    "list_attestations",
]
