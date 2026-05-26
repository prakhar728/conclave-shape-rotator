"""
Dstack agent integration — attestation quotes and output signing.

Inside a Phala CVM the dstack agent exposes a JSON-RPC interface over
a Unix socket (auto-discovered by dstack-sdk; default /var/run/dstack.sock).
Outside the CVM (local dev), or when the socket is unreachable, return
tagged stub values so the service stays up and the operator dashboard
can render honest "broken seal" UI.
"""

import hashlib
import json
import logging
import os

logger = logging.getLogger(__name__)

IN_TEE = os.environ.get("IN_TEE", "false").lower() == "true"
# Optional override for development with the dstack simulator (HTTP endpoint
# like http://localhost:8090) or an explicit socket path.
_DSTACK_ENDPOINT = os.environ.get("DSTACK_AGENT_URL") or None

_client = None
_client_init_failed = False


def _get_client():
    """Lazy-init a single DstackClient. Cache success and (separately) failure
    so we don't spam the SDK on every request."""
    global _client, _client_init_failed
    if _client is not None or _client_init_failed:
        return _client
    try:
        from dstack_sdk import DstackClient

        _client = DstackClient(_DSTACK_ENDPOINT) if _DSTACK_ENDPOINT else DstackClient()
    except Exception as e:
        logger.warning("dstack agent client init failed: %s", e)
        _client_init_failed = True
        _client = None
    return _client


def _normalize_report_data(nonce: str) -> bytes:
    """Pack a string nonce into ≤64 bytes for TDX report_data. SDK rejects
    empty input, so default empty nonces to a fixed 32-byte zero buffer."""
    raw = nonce.encode("utf-8") if nonce else b""
    if not raw:
        return b"\x00" * 32
    if len(raw) > 64:
        return hashlib.sha256(raw).digest()
    return raw


def get_attestation_quote(nonce: str = "") -> str:
    """
    Fetch the TDX attestation quote from the dstack agent.
    Returns hex-encoded quote string.
    Falls back to a tagged stub when not in TEE or the agent is unreachable.
    """
    if not IN_TEE:
        return "stub_attestation_quote_not_in_tee"

    client = _get_client()
    if client is None:
        return "stub_attestation_quote_dstack_unreachable"

    try:
        resp = client.get_quote(_normalize_report_data(nonce))
        return resp.quote
    except Exception as e:
        logger.warning("dstack get_quote failed: %s", e)
        return "stub_attestation_quote_dstack_unreachable"


def sign_result(result: dict) -> tuple[str, str]:
    """
    Sign a result dict inside the TEE using a hardware-bound key, and return
    (signature_hex, attestation_quote_hex). The quote binds the digest into
    hardware-attested state via report_data, so it's verifiable proof that
    *this* enclave saw *this* payload even if Sign RPC isn't supported.
    Falls back to tagged stubs outside the TEE or on failure.
    """
    if not IN_TEE:
        return "stub_signature_not_in_tee", "stub_attestation_quote_not_in_tee"

    payload = json.dumps(result, sort_keys=True).encode()
    digest = hashlib.sha256(payload).digest()
    digest_hex = digest.hex()

    quote = get_attestation_quote(nonce=digest_hex)

    client = _get_client()
    if client is None:
        return "stub_signature_dstack_unreachable", quote

    try:
        sign_resp = client.sign("secp256k1_prehashed", digest)
        return sign_resp.signature, quote
    except Exception as e:
        logger.warning("dstack sign() failed: %s", e)
        return "stub_signature_unsupported", quote
