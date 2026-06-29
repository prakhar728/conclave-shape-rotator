"""Durable job queue (Task #16) — Redis Streams + consumer groups.

A small queue core (`queue.py`) replaces the non-durable in-process background
tasks (`asyncio.create_task`) that ran diarize+identity finalize, enrichment/
regeneration, and the KB build. Jobs now persist in Redis and survive a
Conclave/worker restart; crashed workers' jobs are reclaimed (`XAUTOCLAIM`) and
retried, with a dead-letter after N attempts.

Two streams, one shared core (see `queue.py` docstring for why two):
  - ``diarize_jobs``  — consumed by the **DiariZen GPU worker** (capture repo).
  - ``conclave_jobs`` — consumed by the in-process **Conclave worker** (`worker.py`):
                        enrich / regen / KB index / KB extract.

Every job record (`jobs:{id}` hash) carries a ``type`` field — typed jobs — so a
single stream is multi-purpose. The job hash is the status source of truth.
"""
