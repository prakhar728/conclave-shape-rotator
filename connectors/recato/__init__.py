"""Recato → Conclave canonical-ingest adapter.

Recato (a Vexa fork) is one producer Conclave consumes from. This package
turns Recato's native ``TranscriptionResponse`` (see Recato's
``services/meeting-api/meeting_api/schemas.py`` :: ``TranscriptionResponse``)
into the canonical schema Conclave's ``/transcripts/ingest`` webhook accepts.

Three modes:

- **CLI** (``python -m connectors.recato fetch <platform> <meeting_id>``):
  one-shot fetch + translate + POST. The demo + debugging path.
- **Consumer** (``connectors.recato.consumer``): FastAPI app on a separate
  port that subscribes to Recato's ``meeting.completed`` webhook and runs the
  same flow automatically. The production path.
- **Translator** (``connectors.recato.translator``): pure function used by
  both. Unit-testable without I/O.

Env vars (read from Conclave's ``.env`` or process env):

- ``CONCLAVE_INGEST_URL``      — e.g. ``http://localhost:8000/transcripts/ingest``
- ``CONCLAVE_INGEST_SECRET``   — HMAC-SHA256 signing secret (Conclave side
  reads this as ``CONCLAVE_INGEST_SECRET_RECATO``)
- ``CONCLAVE_INGEST_SOURCE``   — producer id, defaults to ``"recato"``
- ``RECATO_API_BASE_URL``      — e.g. ``http://localhost:8056``
- ``RECATO_API_TOKEN``         — bearer token for Recato's transcript GET
"""
