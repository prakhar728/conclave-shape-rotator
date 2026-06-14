# P4 — Known open work (deferred)

Tracked here so it isn't lost. These are intentionally **not** built for the P4 demo.

## Per-line speaker reassignment ("Case B") — DEFERRED, fuzzy problem

**What it is.** Fixing a *single mis-attributed line*: diarization labelled one sentence
`Speaker 2`, but that sentence was actually spoken by Parth (while the rest of Speaker 2's
lines are correct). The user wants to re-point just that one line to a different person,
in place in the transcript — without renaming the whole speaker.

**Why it's deferred.** It bends the core P4 discipline: *identity lives on the voiceprint,
not on the line*, and a line's speaker label is the immutable join key (architecture §2, C3).
It is also a genuinely fuzzy problem with no single correct solution — the underlying cause is
a diarization under/over-clustering error, and "the right fix" depends on the case (re-cluster
vs. per-line override vs. re-run the post pass).

**What IS built (the common case, "Case A").** Naming a *whole* speaker → the name propagates
in place across every line that speaker said, across all transcripts with that voiceprint, and
binds back to FPM on approval. That is the P4 feedback loop and it is done + gate-verified.

**Candidate designs for later (when we tackle Case B):**
- *Per-line override map* in `SessionMetadata` (e.g. `segment_overrides[segment_index] =
  voiceprint_id|name`) consulted at projection time — keeps `RawSegment.speaker` immutable,
  layers a correction on top. Read path prefers the override, falls back to the label's
  resolved name. Cleanest fit with the existing "name is a read-time projection" model.
- *Re-cluster / split a voiceprint* in FPM when a label conflates two real people — heavier,
  touches the identity store, needs a confidence story.
- *Re-run the post diarize pass* with corrected hints — most accurate, most expensive.

Decision when we get there; for now the demo uses whole-speaker naming only.
