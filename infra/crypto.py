"""Symmetric encryption for provider credentials stored at rest.

Google OAuth refresh tokens are long-lived keys to a user's entire
calendar; storing them in plaintext in SQLite would violate the same
operator-blind posture the LangSmith kill-switch in `config.py` enforces.
This wraps Fernet (AES-128-CBC + HMAC) keyed by `CONCLAVE_TOKEN_ENC_KEY`.

The key is read lazily (not at import) so the app still boots when the
integration is unconfigured — only code paths that actually persist tokens
demand the key, and they fail loud (`TokenEncryptionUnavailable`) rather
than silently writing plaintext.
"""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from config import settings


class TokenEncryptionUnavailable(RuntimeError):
    """Raised when encryption is requested but CONCLAVE_TOKEN_ENC_KEY is unset
    or malformed. Callers should treat this as 'integration not configured'."""


def _fernet() -> Fernet:
    # Not cached: tests (and key rotation) mutate settings.token_enc_key at
    # runtime, and a cached Fernet would silently keep the stale key.
    # Constructing Fernet is cheap (just validates + decodes the key).
    key = settings.token_enc_key
    if not key:
        raise TokenEncryptionUnavailable(
            "CONCLAVE_TOKEN_ENC_KEY is not set — refusing to store provider "
            "credentials in plaintext. Generate one with: python -c "
            '"from cryptography.fernet import Fernet; '
            'print(Fernet.generate_key().decode())"'
        )
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except (ValueError, TypeError) as e:
        raise TokenEncryptionUnavailable(
            f"CONCLAVE_TOKEN_ENC_KEY is malformed (must be a 32-byte "
            f"url-safe base64 Fernet key): {e}"
        ) from e


def encrypt(plaintext: str) -> str:
    """Encrypt a UTF-8 string → url-safe base64 token (str)."""
    return _fernet().encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt a token produced by `encrypt`. Raises TokenEncryptionUnavailable
    on a wrong/rotated key so callers can prompt the user to reconnect rather
    than crash with a bare InvalidToken."""
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise TokenEncryptionUnavailable(
            "Stored credential could not be decrypted (key rotated or data "
            "corrupt) — the user must reconnect."
        ) from e


def available() -> bool:
    """True when a usable encryption key is configured. Cheap probe for
    routes that want to 503 early instead of raising mid-write."""
    try:
        _fernet()
        return True
    except TokenEncryptionUnavailable:
        return False
