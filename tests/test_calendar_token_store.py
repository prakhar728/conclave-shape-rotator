"""Step 1 — crypto round-trip + encrypted token store.

Verifies tokens are encrypted at rest (ciphertext != plaintext in the DB),
decrypt back cleanly, that a refresh-without-refresh-token preserves the
stored refresh token, and that disconnect wipes the row.
"""
from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from storage.sqlite import _get_conn


@pytest.fixture(autouse=True)
def _enc_key(monkeypatch):
    """Give the token store a real Fernet key + a user row to FK against."""
    from config import settings
    monkeypatch.setattr(settings, "token_enc_key", Fernet.generate_key().decode())
    from tests.conftest import reset_workspace_domain_tables
    _get_conn().execute("DELETE FROM google_oauth_tokens")
    reset_workspace_domain_tables()
    from infra import identity, workspaces
    user = identity.upsert_user_by_supabase(supabase_id="sb-cal", email="cal@example.com")
    workspaces.ensure_personal_workspace(user["id"])
    yield user["id"]


def test_crypto_round_trip(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "token_enc_key", Fernet.generate_key().decode())
    from infra import crypto
    token = crypto.encrypt("super-secret-refresh")
    assert token != "super-secret-refresh"
    assert crypto.decrypt(token) == "super-secret-refresh"


def test_crypto_without_key_raises(monkeypatch):
    from config import settings
    monkeypatch.setattr(settings, "token_enc_key", "")
    from infra import crypto
    assert crypto.available() is False
    with pytest.raises(crypto.TokenEncryptionUnavailable):
        crypto.encrypt("x")


def test_save_and_get_tokens(_enc_key):
    user_id = _enc_key
    from infra import google_calendar as gc
    gc.save_tokens(
        user_id=user_id,
        access_token="acc-1",
        refresh_token="ref-1",
        expiry="2026-06-08T12:00:00+00:00",
        scopes="calendar.events",
    )
    got = gc.get_tokens(user_id)
    assert got["access_token"] == "acc-1"
    assert got["refresh_token"] == "ref-1"
    assert got["expiry"] == "2026-06-08T12:00:00+00:00"
    assert gc.is_connected(user_id) is True
    assert user_id in gc.list_connected_user_ids()


def test_tokens_encrypted_at_rest(_enc_key):
    user_id = _enc_key
    from infra import google_calendar as gc
    gc.save_tokens(user_id=user_id, access_token="acc-plain",
                   refresh_token="ref-plain", expiry=None, scopes="")
    row = _get_conn().execute(
        "SELECT access_token_enc, refresh_token_enc FROM google_oauth_tokens WHERE user_id = ?",
        (user_id,),
    ).fetchone()
    # Ciphertext must not contain the plaintext.
    assert "acc-plain" not in (row["access_token_enc"] or "")
    assert "ref-plain" not in (row["refresh_token_enc"] or "")


def test_refresh_preserves_existing_refresh_token(_enc_key):
    user_id = _enc_key
    from infra import google_calendar as gc
    gc.save_tokens(user_id=user_id, access_token="acc-1",
                   refresh_token="ref-original", expiry="t1", scopes="s")
    # Simulate a token refresh: new access token, NO refresh token returned.
    gc.save_tokens(user_id=user_id, access_token="acc-2",
                   refresh_token=None, expiry="t2", scopes="s")
    got = gc.get_tokens(user_id)
    assert got["access_token"] == "acc-2"
    assert got["refresh_token"] == "ref-original"  # preserved
    assert got["expiry"] == "t2"


def test_disconnect_wipes_tokens(_enc_key):
    user_id = _enc_key
    from infra import google_calendar as gc
    gc.save_tokens(user_id=user_id, access_token="a", refresh_token="r",
                   expiry=None, scopes="")
    gc.delete_tokens(user_id)
    assert gc.get_tokens(user_id) is None
    assert gc.is_connected(user_id) is False
