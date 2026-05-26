"""Solana devnet attestation publication.

Publishes a SHA-256 hash of the final cohort report to Solana devnet using the
SPL Memo program. The transaction itself becomes the attestation: anyone can
look it up by signature, read the memo, and verify the signer pubkey is the
enclave's known service key (ideally part of the TDX measurement).

Why memo and not a custom Anchor program: simpler, no deployment, identical
verification semantics. The signed-tx-with-known-payload pattern is what
matters; on-chain code is unnecessary for a recordkeeping use case.

Configuration via env:
- CONCLAVE_SOLANA_KEYPAIR  — base58-encoded 64-byte secret (solana CLI format)
- CONCLAVE_SOLANA_RPC_URL  — defaults to https://api.devnet.solana.com
- CONCLAVE_SOLANA_NETWORK  — defaults to "devnet" (used for explorer URL)

If the keypair env var is unset, publish_attestation() returns a "local_only"
record and skips the network call. This keeps the dev/test path running
without Solana and lets the enclave operator opt in by setting the keypair.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

MEMO_PROGRAM_ID = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
DEFAULT_RPC = "https://api.devnet.solana.com"
DEFAULT_NETWORK = "devnet"


def is_configured() -> bool:
    return bool(os.environ.get("CONCLAVE_SOLANA_KEYPAIR"))


def hash_report(results: list[dict]) -> bytes:
    """Deterministic SHA-256 of the cohort report. Sorted by submission_id."""
    sorted_results = sorted(results, key=lambda r: r.get("submission_id", ""))
    payload = json.dumps(sorted_results, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(payload).digest()


def _explorer_url(tx_sig: str, network: str) -> str:
    return f"https://explorer.solana.com/tx/{tx_sig}?cluster={network}"


def _load_keypair():
    """Decode the configured keypair (base58 or JSON-array form)."""
    from solders.keypair import Keypair  # type: ignore

    raw = os.environ.get("CONCLAVE_SOLANA_KEYPAIR", "").strip()
    if not raw:
        raise RuntimeError("CONCLAVE_SOLANA_KEYPAIR not set")
    if raw.startswith("["):
        # Solana CLI keygen format: JSON array of 64 ints
        return Keypair.from_bytes(bytes(json.loads(raw)))
    # Try base58
    try:
        import base58  # type: ignore
        return Keypair.from_bytes(base58.b58decode(raw))
    except Exception:
        # Last resort: base64
        return Keypair.from_bytes(base64.b64decode(raw))


def publish_attestation(report_hash: bytes) -> dict[str, Any]:
    """Publish a memo-bearing transaction to Solana devnet.

    Returns {tx_sig, pubkey, explorer_url, chain, status, report_hash_hex}.
    Status is 'published' on success, 'local_only' if Solana is unconfigured,
    or 'failed' if the broadcast errored (we still return locally).
    """
    network = os.environ.get("CONCLAVE_SOLANA_NETWORK") or DEFAULT_NETWORK
    rpc_url = os.environ.get("CONCLAVE_SOLANA_RPC_URL") or DEFAULT_RPC
    report_hash_hex = report_hash.hex()

    if not is_configured():
        logger.info("solana: keypair unconfigured, recording local-only attestation")
        return {
            "tx_sig": None,
            "pubkey": None,
            "explorer_url": None,
            "chain": f"solana-{network}",
            "status": "local_only",
            "report_hash_hex": report_hash_hex,
        }

    try:
        import base64 as _b64
        import httpx
        from solders.instruction import Instruction, AccountMeta  # type: ignore
        from solders.message import Message  # type: ignore
        from solders.hash import Hash  # type: ignore
        from solders.pubkey import Pubkey  # type: ignore
        from solders.transaction import Transaction  # type: ignore

        keypair = _load_keypair()
        memo_payload = f"conclave-attestation:{report_hash_hex}".encode("utf-8")

        instruction = Instruction(
            program_id=Pubkey.from_string(MEMO_PROGRAM_ID),
            accounts=[AccountMeta(pubkey=keypair.pubkey(), is_signer=True, is_writable=False)],
            data=memo_payload,
        )

        # Force IPv4 source binding — the Phala CVM network can't allocate an
        # IPv6 source address when the RPC hostname returns AAAA records.
        # We bypass solana-py's HTTP layer (which uses default httpx config)
        # and drive the RPC directly with a transport pinned to 0.0.0.0.
        transport = httpx.HTTPTransport(local_address="0.0.0.0")
        with httpx.Client(transport=transport, timeout=15) as rpc:
            blockhash_resp = rpc.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getLatestBlockhash",
                    "params": [{"commitment": "confirmed"}],
                },
            )
            blockhash_resp.raise_for_status()
            blockhash_str = blockhash_resp.json()["result"]["value"]["blockhash"]
            recent_blockhash = Hash.from_string(blockhash_str)

            message = Message.new_with_blockhash([instruction], keypair.pubkey(), recent_blockhash)
            tx = Transaction([keypair], message, recent_blockhash)
            tx_b64 = _b64.b64encode(bytes(tx)).decode("ascii")

            send_resp = rpc.post(
                rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "sendTransaction",
                    "params": [tx_b64, {"encoding": "base64", "preflightCommitment": "confirmed"}],
                },
            )
            send_resp.raise_for_status()
            send_body = send_resp.json()
            if "error" in send_body:
                raise RuntimeError(f"sendTransaction RPC error: {send_body['error']}")
            tx_sig = send_body["result"]

        return {
            "tx_sig": tx_sig,
            "pubkey": str(keypair.pubkey()),
            "explorer_url": _explorer_url(tx_sig, network),
            "chain": f"solana-{network}",
            "status": "published",
            "report_hash_hex": report_hash_hex,
        }
    except Exception as e:
        logger.error("solana: publish failed: %s", e, exc_info=True)
        return {
            "tx_sig": None,
            "pubkey": None,
            "explorer_url": None,
            "chain": f"solana-{network}",
            "status": "failed",
            "report_hash_hex": report_hash_hex,
            "error": str(e),
        }
