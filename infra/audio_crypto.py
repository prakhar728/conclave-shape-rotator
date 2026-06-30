"""AES-256-CBC + HMAC-SHA256 at-rest encryption for stored meeting audio (Task #30).

Mirrors FPM's `fpm/store/crypto.py` (the voiceprint-store seal) — one cross-platform
backend (PyCA `cryptography`), encrypt-then-MAC, HKDF-derived enc/mac subkeys, a 4-byte
MAGIC so reads can tell an encrypted blob from a legacy plaintext chunk and fall back.

This is deliberately NOT `infra/crypto.py` (Fernet / AES-128, for OAuth tokens): audio is
the product's most sensitive artifact, so it gets AES-256 under a TEE-sealed key, the same
posture as the voiceprints it's derived from.

BLOB format:  MAGIC(4) || IV(16) || HMAC-SHA256(32) || ciphertext
Random IV per blob. Each audio CHUNK is encrypted independently (so reads decrypt
chunk-by-chunk and can mix encrypted + legacy-plaintext chunks during the no-retro window).

Key resolution (`get_or_create_key`), in priority order:
  1. dstack-SEALED key in a TEE (`IN_TEE=true`) — bound to this CVM, never on disk. Prod.
  2. `CONCLAVE_AUDIO_ENC_KEY` env (64 hex chars / 32 bytes, or base64) — explicit / non-TEE.
  3. 0600 dev keyfile under CONCLAVE_AUDIO_DIR — local dev fallback.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives import padding as _pad
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

_MAGIC = b"CAE1"  # Conclave Audio Encryption v1
_IV_LEN = 16
_HMAC_LEN = 32
_KEY_LEN = 32
_HEADER_LEN = len(_MAGIC) + _IV_LEN + _HMAC_LEN
_ENC_LABEL = b"conclave-audio-enc-v1"
_MAC_LABEL = b"conclave-audio-mac-v1"


def _hkdf_expand(master: bytes, label: bytes, length: int = 32) -> bytes:
    return hmac.new(master, label + b"\x01", hashlib.sha256).digest()[:length]


def derive_keys(master: bytes) -> tuple[bytes, bytes]:
    return _hkdf_expand(master, _ENC_LABEL), _hkdf_expand(master, _MAC_LABEL)


def _aes(op: str, key: bytes, iv: bytes, data: bytes) -> bytes:
    cipher = Cipher(algorithms.AES(key), modes.CBC(iv))
    if op == "enc":
        padder = _pad.PKCS7(128).padder()
        padded = padder.update(data) + padder.finalize()
        enc = cipher.encryptor()
        return enc.update(padded) + enc.finalize()
    dec = cipher.decryptor()
    padded = dec.update(data) + dec.finalize()
    unpadder = _pad.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def is_encrypted(data: bytes) -> bool:
    """True iff `data` carries the Conclave audio MAGIC header (vs legacy plaintext)."""
    return bool(data) and len(data) >= _HEADER_LEN + 1 and data[: len(_MAGIC)] == _MAGIC


def encrypt_blob(master: bytes, plaintext: bytes) -> bytes:
    if not plaintext:
        return b""
    enc_key, mac_key = derive_keys(master)
    iv = os.urandom(_IV_LEN)
    ciphertext = _aes("enc", enc_key, iv, plaintext)
    tag = hmac.new(mac_key, _MAGIC + iv + ciphertext, hashlib.sha256).digest()
    return _MAGIC + iv + tag + ciphertext


def decrypt_blob(master: bytes, data: bytes) -> bytes:
    if not data:
        return b""
    if not is_encrypted(data):
        raise ValueError("not a Conclave-encrypted audio blob")
    iv = data[len(_MAGIC) : len(_MAGIC) + _IV_LEN]
    stored = data[len(_MAGIC) + _IV_LEN : _HEADER_LEN]
    ciphertext = data[_HEADER_LEN:]
    enc_key, mac_key = derive_keys(master)
    expected = hmac.new(mac_key, _MAGIC + iv + ciphertext, hashlib.sha256).digest()
    if not hmac.compare_digest(stored, expected):
        raise ValueError("integrity check failed — tampered data or wrong key")
    return _aes("dec", enc_key, iv, ciphertext)


def _audio_dir() -> Path:
    return Path(os.environ.get("CONCLAVE_AUDIO_DIR", "data/audio"))


def get_or_create_key() -> bytes:
    """Master key for at-rest audio encryption (see module docstring for order)."""
    from infra import enclave

    sealed = enclave.get_sealed_key()
    if sealed is not None:
        if len(sealed) != _KEY_LEN:  # enclave returns sha256 → always 32, but be safe
            raise ValueError("sealed audio key must be 32 bytes")
        return sealed

    from config import settings

    env = settings.audio_enc_key or os.environ.get("CONCLAVE_AUDIO_ENC_KEY", "")
    if env:
        key = bytes.fromhex(env) if len(env) == 64 else base64.b64decode(env)
        if len(key) != _KEY_LEN:
            raise ValueError("CONCLAVE_AUDIO_ENC_KEY must decode to 32 bytes (64 hex chars)")
        return key

    key_path = _audio_dir() / ".conclave-audio.key"
    if key_path.exists():
        return key_path.read_bytes()
    key_path.parent.mkdir(parents=True, exist_ok=True)
    key = os.urandom(_KEY_LEN)
    fd, tmp = tempfile.mkstemp(dir=key_path.parent, prefix=".audiokey_")
    try:
        if hasattr(os, "fchmod"):
            os.fchmod(fd, 0o600)
        os.write(fd, key)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, key_path)
    return key


def encrypt(plaintext: bytes) -> bytes:
    """Encrypt one audio chunk with the resolved master key."""
    return encrypt_blob(get_or_create_key(), plaintext)


def decrypt_if_encrypted(data: bytes) -> bytes:
    """Decrypt a stored chunk if it carries our MAGIC; pass plaintext through unchanged.

    This is the new-meetings-only read seam: legacy plaintext files (written before #30)
    keep playing, while new encrypted chunks are transparently decrypted on read.
    """
    if not is_encrypted(data):
        return data
    return decrypt_blob(get_or_create_key(), data)
