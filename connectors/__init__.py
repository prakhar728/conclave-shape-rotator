"""Producer-side adapters that POST to Conclave's canonical ingest webhook.

Each subpackage here translates one producer's native transcript format into
the canonical schema (``STRATEGY.md`` Appendix A.3). Conclave itself stays
unaware of these — they're public, third-party-shaped code that happens to
ship in the same repo because we maintain a couple of them.

Conventions:
- A ``translator.py`` module exposing ``to_canonical(...) -> dict`` (pure).
- A ``cli.py`` for one-shot ``fetch + translate + POST`` invocation (demo).
- An optional ``consumer.py`` for the webhook-driven mode (production).
"""
