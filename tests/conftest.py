"""
Shared pytest configuration for the Conclave test suite.

Provides:
  - @pytest.mark.live  — skip when CONCLAVE_NEARAI_API_KEY is not set
  - base_df            — session-scoped fraud-like DataFrame (~800 rows)
  - matrix_results     — session-scoped list; tests append rows, teardown
                         prints two tables and saves tests/demo_matrix.json

**Safety**: routes every test through an isolated temp SQLite DB so no
test (including unscoped `storage.reset_all()` calls in test_e2e /
test_scheduler / test_attestation / interview_reflection fixtures) can
ever wipe the user's real `data/conclave.db`. Set at module-import time
so the env var lands before any test file does `import storage`.
"""
from __future__ import annotations

import datetime
import json
import os
import tempfile
from typing import Generator

import pandas as pd
import pytest


# ---------------------------------------------------------------------------
# DB ISOLATION (loaded before any test module — keep at top of conftest)
# ---------------------------------------------------------------------------
# `storage/sqlite.py` reads CONCLAVE_DB_PATH at module-import time. Setting
# it here, in conftest, means by the time pytest collects any test file
# (which is where `import storage` happens) the env already points at a
# temp DB. Belt: we *also* force-overwrite sqlite._DB_PATH right after the
# first import, in case some module was eagerly imported before conftest.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="conclave-tests-")
_TEST_DB_PATH = os.path.join(_TEST_DB_DIR, "test.db")
os.environ["CONCLAVE_DB_PATH"] = _TEST_DB_PATH

try:
    from storage import sqlite as _sqlite
    _sqlite._DB_PATH = _TEST_DB_PATH
    _sqlite._conn = None
    # Force _init_schema to run NOW so the legacy `transcript_sessions` table
    # exists before alembic's 0004 tries to ALTER it. Order matters: legacy
    # schema must land before alembic-owned migrations touch it.
    _sqlite._get_conn()
except Exception:  # noqa: BLE001 — if storage isn't importable, nothing to protect
    pass

# Alembic-owned tables (Phase 1.3+) need an explicit upgrade — they're not
# in storage.sqlite._init_schema. Run migrations against the per-process
# test DB so any test touching infra/identity or infra/workspaces sees the
# `users`/`workspaces`/etc tables. Cheap (~50ms) and runs once at import.
try:
    from alembic.config import Config as _AlembicConfig
    from alembic import command as _alembic_command

    _alembic_cfg = _AlembicConfig(
        os.path.join(os.path.dirname(__file__), "..", "alembic.ini")
    )
    # Point Alembic at the test DB explicitly — env.py reads CONCLAVE_DB_URL.
    os.environ["CONCLAVE_DB_URL"] = f"sqlite:///{_TEST_DB_PATH}"
    _alembic_command.upgrade(_alembic_cfg, "head")
except Exception as _e:  # noqa: BLE001 — alembic optional; legacy tests still pass
    import sys as _sys
    print(f"[conftest] alembic upgrade skipped: {_e}", file=_sys.stderr)

DEMO_JSON_PATH = os.path.join(os.path.dirname(__file__), "demo_matrix.json")


# ---------------------------------------------------------------------------
# Shared cleanup helper
# ---------------------------------------------------------------------------

def reset_workspace_domain_tables() -> None:
    """Wipe the workspace-domain tables (users/workspaces/sessions/etc.) safely.

    Phase 1.6 added FK references from `transcript_sessions` to `workspaces`
    and `users`. Nulling those columns first lets per-test fixtures delete
    user/workspace rows without tripping the constraint. The
    `transcript_sessions` rows themselves stay — different tests own those.
    """
    try:
        from storage.sqlite import _get_conn
    except Exception:  # noqa: BLE001
        return
    conn = _get_conn()
    conn.execute(
        "UPDATE transcript_sessions SET workspace_id = NULL, owner_user_id = NULL"
    )
    for table in (
        "sessions",
        "meeting_shares",
        "magic_links",
        "bot_invitations",
        "workspace_invites",  # else an orphaned invite (→ deleted ws/user) FK-fails a later accept
        "workspace_members",
        "workspaces",
        "users",
    ):
        try:
            conn.execute(f"DELETE FROM {table}")
        except Exception:  # noqa: BLE001 — table may not exist in legacy-only DBs
            pass


# ---------------------------------------------------------------------------
# Markers
# ---------------------------------------------------------------------------

def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "live: mark test as requiring a real NearAI API key (skipped in CI)",
    )
    config.addinivalue_line(
        "markers",
        "requires_ollama: mark test as requiring a reachable local Ollama daemon "
        "with the configured CONCLAVE_OLLAMA_MODEL pulled. Auto-skipped otherwise.",
    )
    config.addinivalue_line(
        "markers",
        "requires_spacy: mark test as requiring spacy + the en_core_web_sm model "
        "(Part 1 candidate detection). Auto-skipped otherwise.",
    )


def _ollama_ready() -> tuple[bool, str]:
    """Return (ready, reason). Used both by the marker hook and by tests
    that want to assert the local model is the one they expect."""
    try:
        import json as _json
        import urllib.request as _urllib
        from config import settings as _s
        root = _s.ollama_base_url.rstrip("/")
        if root.endswith("/v1"):
            root = root[: -len("/v1")]
        with _urllib.urlopen(f"{root}/api/tags", timeout=2) as r:
            tags = [m.get("name", "") for m in _json.load(r).get("models", [])]
        wanted = _s.ollama_model if ":" in _s.ollama_model else f"{_s.ollama_model}:latest"
        if wanted in tags or _s.ollama_model in tags:
            return True, ""
        return False, f"Ollama reachable but model {_s.ollama_model!r} not pulled"
    except Exception as exc:  # noqa: BLE001 — any failure means "not ready"
        return False, f"Ollama not reachable: {type(exc).__name__}: {exc}"


def _spacy_ready() -> tuple[bool, str]:
    """Return (ready, reason). Checks the model is installed WITHOUT loading it
    (is_package is cheap), so non-spacy runs don't pay the ~1s model load."""
    try:
        import spacy
        if spacy.util.is_package("en_core_web_sm"):
            return True, ""
        return False, "en_core_web_sm not installed (python -m spacy download en_core_web_sm)"
    except Exception as exc:  # noqa: BLE001
        return False, f"spacy unavailable: {type(exc).__name__}: {exc}"


def pytest_collection_modifyitems(config, items):
    api_key = os.environ.get("CONCLAVE_NEARAI_API_KEY", "").strip()
    skip_live = pytest.mark.skip(reason="CONCLAVE_NEARAI_API_KEY not set — live tests skipped")

    ollama_ready, ollama_reason = _ollama_ready()
    skip_ollama = pytest.mark.skip(reason=f"requires_ollama: {ollama_reason}")

    spacy_ready, spacy_reason = _spacy_ready()
    skip_spacy = pytest.mark.skip(reason=f"requires_spacy: {spacy_reason}")

    for item in items:
        if "live" in item.keywords and not api_key:
            item.add_marker(skip_live)
        if "requires_ollama" in item.keywords and not ollama_ready:
            item.add_marker(skip_ollama)
        if "requires_spacy" in item.keywords and not spacy_ready:
            item.add_marker(skip_spacy)


# ---------------------------------------------------------------------------
# Dataset fixture
#
# Loads dazzle-nu/CIS435-CreditCardFraudDetection from HuggingFace.
# Normalises to: transaction_id, amount, is_fraud, category, merchant
# PII columns retained but NOT included by default — seller variants
# can add them (dob, cc_num) to trigger the forbidden-column rejection.
#
# Falls back to synthetic data if HuggingFace is unavailable (e.g. CI).
# ---------------------------------------------------------------------------

_HF_DATASET = "dazzle-nu/CIS435-CreditCardFraudDetection"
_SAMPLE_N   = 1000


def _generate_synthetic_df(n: int = _SAMPLE_N) -> pd.DataFrame:
    import numpy as np
    rng = np.random.default_rng(42)
    return pd.DataFrame({
        "transaction_id": [f"txn_{i:05d}" for i in range(n)],
        "amount":         rng.uniform(1.0, 500.0, n).round(2),
        "category":       rng.choice(["grocery", "gas", "restaurant", "travel", "online"], n),
        "merchant":       [f"merchant_{i % 50}" for i in range(n)],
        "is_fraud":       (rng.uniform(0, 1, n) < 0.04).astype(int),
        # PII cols — available for forbidden-column tests
        "dob":            [f"19{(i % 60 + 40):02d}-01-01" for i in range(n)],
        "cc_num":         [f"4{i:015d}" for i in range(n)],
    })


def _load_hf_df() -> pd.DataFrame | None:
    try:
        from datasets import load_dataset
        ds = load_dataset(_HF_DATASET, split="train")
        df = ds.to_pandas()

        # Normalise column names
        df = df.rename(columns={"trans_num": "transaction_id", "amt": "amount"})
        if "transaction_id" not in df.columns:
            df.insert(0, "transaction_id", [f"txn_{i:06d}" for i in range(len(df))])

        required = {"transaction_id", "amount", "is_fraud"}
        if not required.issubset(df.columns):
            return None

        # Stratified sample: keep fraud/non-fraud ratio, cap at _SAMPLE_N
        fraud    = df[df["is_fraud"] == 1].sample(min(40, (df["is_fraud"] == 1).sum()), random_state=42)
        nonfraud = df[df["is_fraud"] == 0].sample(_SAMPLE_N - len(fraud), random_state=42)
        df = pd.concat([fraud, nonfraud]).sample(frac=1, random_state=42).reset_index(drop=True)

        print(f"[conftest] HuggingFace dataset loaded: {len(df)} rows, "
              f"fraud rate={df['is_fraud'].mean():.1%}, columns={list(df.columns)}")
        return df
    except Exception as e:
        print(f"[conftest] HuggingFace load failed ({e}) — using synthetic data")
        return None


@pytest.fixture(scope="session")
def base_df() -> pd.DataFrame:
    """
    Session-scoped DataFrame from dazzle-nu/CIS435-CreditCardFraudDetection (~1000 rows).
    Falls back to synthetic if HuggingFace is unavailable.
    """
    df = _load_hf_df()
    return df if df is not None else _generate_synthetic_df()


# ---------------------------------------------------------------------------
# Matrix results fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def matrix_results() -> Generator[list[dict], None, None]:
    """
    Session-scoped list. Tests append rows with a "type" field:
      type="evaluation"    — pipeline runs (quality, payment, deal)
      type="renegotiation" — post-evaluation negotiation rounds

    At teardown: prints two formatted tables + saves tests/demo_matrix.json.
    """
    rows: list[dict] = []
    yield rows

    if not rows:
        return

    eval_rows  = [r for r in rows if r.get("type") != "renegotiation"]
    reneg_rows = [r for r in rows if r.get("type") == "renegotiation"]

    # --- Evaluation table ---
    if eval_rows:
        print("\n" + "=" * 96)
        print("EVALUATION MATRIX  (deterministic + LLM agent)")
        print("=" * 96)
        print(f"{'Scenario':<30} {'Seller':<18} {'Buyer':<12} {'Reserve':>8} {'Quality':>8} {'Payment':>9} {'Deal':>5}")
        print("-" * 96)
        for r in eval_rows:
            q   = r.get("quality")
            p   = r.get("payment")
            rv  = r.get("reserve")
            print(
                f"{r.get('scenario',''):<30} {r.get('seller',''):<18} {r.get('buyer',''):<12} "
                f"{'$'+f'{rv:,.0f}' if rv is not None else 'N/A':>8} "
                f"{f'{q:.3f}' if q is not None else 'N/A':>8} "
                f"{'$'+f'{p:,.0f}' if p is not None else 'N/A':>9} "
                f"{'YES' if r.get('deal') else ' NO':>5}"
            )
        print("=" * 96)

    # --- Renegotiation table ---
    if reneg_rows:
        print("\n" + "=" * 90)
        print("RENEGOTIATION MATRIX  (post-evaluation, deterministic only)")
        print("=" * 90)
        print(f"{'Scenario':<35} {'Initial':>9} {'Buyer':>14} {'Seller':>14} {'Final':>9} {'Deal':>5}")
        print("-" * 90)
        for r in reneg_rows:
            init = r.get("initial_offer")
            final = r.get("final_payment")
            print(
                f"{r.get('scenario',''):<35} "
                f"{'$'+f'{init:,.0f}' if init is not None else 'N/A':>9} "
                f"{str(r.get('buyer_action','')):<14} "
                f"{str(r.get('supplier_action','')):<14} "
                f"{'$'+f'{final:,.0f}' if final is not None else '  —':>9} "
                f"{'YES' if r.get('deal') else ' NO':>5}"
            )
        print("=" * 90)

    # --- Save JSON ---
    # Pull buyer prompt from first eval row if present (set by test_live_e2e.py)
    buyer_prompt = eval_rows[0].get("buyer_prompt") if eval_rows else None

    output = {
        "title":     "Confidential Data Procurement — Demo Results",
        "generated": str(datetime.date.today()),
        "model":     "deepseek-ai/DeepSeek-V3.1",
        "pipeline":  "deterministic → LLM agent (schema match + claim verify) → guardrails",
        "note":      "base_price=0: bad data → payment approaches $0. Reserve not met → deal rejected.",
        "buyer_prompt": buyer_prompt,
        "evaluation_matrix": [
            {
                "id":             i + 1,
                "scenario":       r.get("scenario", ""),
                "narrative":      r.get("narrative", ""),
                "seller_variant": r.get("seller", ""),
                "buyer_variant":  r.get("buyer", ""),
                "seller_input":   r.get("seller_input"),
                "reserve_price":  r.get("reserve"),
                "quality_score":  round(r["quality"], 4) if r.get("quality") is not None else None,
                "proposed_payment": r.get("payment"),
                "deal":           r.get("deal"),
                "settlement_status": "pending_approval" if r.get("deal") else "rejected",
                "notes":          r.get("notes", []),
                "explanation":    r.get("explanation", ""),
                "schema_matching":    r.get("schema_matching"),
                "claim_verification": r.get("claim_verification"),
            }
            for i, r in enumerate(eval_rows)
        ],
        "renegotiation_matrix": [
            {
                "id":             i + 1,
                "scenario":       r.get("scenario", ""),
                "narrative":      r.get("narrative", ""),
                "initial_offer":  r.get("initial_offer"),
                "buyer_action":   r.get("buyer_action", ""),
                "supplier_action":r.get("supplier_action", ""),
                "final_payment":  r.get("final_payment"),
                "deal":           r.get("deal"),
                "settlement_status": "authorized" if r.get("deal") else "rejected",
            }
            for i, r in enumerate(reneg_rows)
        ],
    }
    with open(DEMO_JSON_PATH, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nDemo JSON → {DEMO_JSON_PATH}")
