"""Terms & Conditions copy + version (Task #18).

Single source of truth for the early-access T&C. The blocking first-login gate
and the Settings mirror both render :data:`TNC_TEXT`; acceptance is recorded
against :data:`TNC_VERSION` (see ``infra.identity.accept_tnc``). Bump the
version string here (and add the new copy) when the terms change — every user
whose recorded ``tnc_version`` no longer matches re-sees the gate.

The ``tnc-v0`` copy is a Claude-drafted placeholder for the testing period; a
full legal pass replaces it before general availability (TASK-18 §0a).
"""
from __future__ import annotations

#: Current terms version. Acceptance is recorded against this string; the gate
#: re-fires for any user whose stored version differs.
TNC_VERSION = "tnc-v0"

#: Verbatim placeholder copy (TASK-18 §0a). Rendered by the gate + Settings.
TNC_TEXT = """\
Terms & Conditions — Early Access (pre-production)

Conclave is in active development and provided for testing. By continuing you acknowledge:

- This is pre-production software — data (transcripts, summaries, voiceprints) may be deleted or wiped at any time without notice as we test and iterate.
- Don't rely on it as a system of record — keep your own copies; you can export your data anytime from Settings.
- Recordings capture other people's voices — only record with the consent of everyone present, per your local laws.
- Provided as-is, without warranty; we're not liable for data loss during this testing phase.
- These are placeholder terms for the testing period and will be replaced by full legal terms before general availability.
"""
