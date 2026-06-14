# Branch B — voiceprint_id persistence + name projection (P2)

**Repo:** Conclave · **Base:** `main` (`feat/consent-plane`) · **Autonomy:** agent-autonomous
(test-first) · **Depends on:** Contracts **C2** (consumes `/v1/diarize` `voiceprint_id`) + **C3**
(`resolved_speakers` schema). **Conclave-only — touches no FPM code.** Unblocks the whole feedback
loop and is on the critical path (B → P4 → P5).

> **Status of this doc:** ARCHITECTURE.md is the frozen spine; per its rule, all enrichment and
> deviations are recorded *here*. This file was enriched on 2026-06-13 after a full read of the
> current ingest path. The architecture lists branch plans under `docs/build/`; the actual location
> is `docs/plans/` — same content, no behavioural difference. Keep both consistent if `docs/build/`
> is ever created.

## Goal
Stop dropping `voiceprint_id`. Persist it per speaker so identity edits (P4) and redaction (P5) have
a stable key, and make the display name a pure read-time projection.

---

## 0. Current-state audit (what's built vs. what B must build)

Read this before touching anything — the seam where `voiceprint_id` dies is **not** where the
original one-line plan implied.

### What already exists and works
- **`/v1/diarize` is already consumed.** `api/record_routes.py:_fpm_diarize` (L91–116) parses the
  C2 NDJSON, prefers the final `{"type":"transcript","segments":[...]}` view, and returns identity
  segments that **already carry `voiceprint_id`, `name`, `confidence`, `local_speaker`** (verified:
  `tests/test_record_routes.py:_IDENTITY` fixtures carry `vp_a/vp_b/vp_c`).
- **The merge runs and labels correctly.** `merge_by_timestamp` (L54–88) assigns each ASR segment a
  display label (`name` when present, else `Speaker N`) via `_best_overlap`.
- **The read path already projects name onto the transcript.** `api/transcripts_routes.py:to_transcript`
  (L288–318) maps `resolved_speakers[label]["name"]` onto each segment as `speaker_name`, **without**
  rewriting `seg.speaker` (the immutable join key). `to_card`/`to_view` already pass the full
  `resolved_speakers` dict through to the client.
- **`resolved_speakers` is already mutable JSON** (`SessionMetadata.resolved_speakers: dict[str, Any]`,
  `models.py:38`). **No SQL migration needed** — C3 lands as a value-shape convention only.
- **`said_by` is never rewritten** anywhere — signals carry verbatim labels; names are projected at
  read time. This invariant is already honoured; B must not break it.

### The three places `voiceprint_id` is dropped today (the real work)
1. **`merge_by_timestamp` collapses each segment to `{speaker, text, start, end}`** (L82–87) — the
   `voiceprint_id` from the identity segment is discarded at the merge.
2. **The record path round-trips the merged list through the *upload* parser.** `record_meeting`
   (L204–214) does `text = json.dumps(merged)` → `UploadTranscriptBody` → `_parse_upload` →
   `sources.read_obj` → `_normalize_json_segment` (`sources.py:223–243`), which **only keeps
   `{speaker, text, start, end}`**. So even if step 1 preserved `voiceprint_id` on each merged
   segment, it would be **stripped on the re-parse**. ⇒ `voiceprint_id` **cannot** travel via the
   segment list / `RawSegment`. (This is *correct* per architecture: `RawSegment` is immutable and
   `voiceprint_id` must live in `resolved_speakers`, **not** on the raw segment.)
3. **`record_meeting` calls the *cohort* resolver** `resolve_speakers(session)` (L229) — that's
   `identity.resolve_speakers`, which name-matches labels against `MOCK_DIRECTORY` and emits
   `{record_id, name, mock}`. For a recorded meeting the labels are FPM emails/names or `Speaker N`,
   which don't match the cohort roster → it produces an (almost always) **empty** dict and carries
   **no `voiceprint_id`**. Wrong keyspace for this path.

**Design consequence (the load-bearing decision):** `voiceprint_id` must be written into
`resolved_speakers` **directly inside `record_routes.py`, from the in-memory identity segments,
before/around the merge** — a side channel that never goes through `_parse_upload`/`RawSegment`. The
existing `to_transcript` projection then works unchanged because it keys on the display label, which
is identical on both sides (built by the same labelling function).

---

## 1. Design

### 1.1 Shared deterministic labelling (the core of steps 1–2)
Today numbering is **first-appearance** (`index.setdefault(key_of(d), len(index)+1)`, L66–68) and
`key_of` prefers `local_speaker` (L63–64). Two problems for the live→post swap: (a) first-appearance
order differs between the live (diart) and post (DiariZen) passes, and (b) `local_speaker` is
engine-private and differs across engines. Both make `Speaker N` reshuffle when post replaces live.

**Fix:** number deterministically by a **stable cross-pass key**, preferring `voiceprint_id`:

```python
def _speaker_key(d: dict) -> str:
    # voiceprint_id is the cross-pass-stable identity; local_speaker is the
    # within-pass fallback for segments the post pass hasn't minted yet
    # (live read-only mints nothing → voiceprint_id may be None there).
    return d.get("voiceprint_id") or d.get("local_speaker") or "spk"

def _label_index(identity_segments: list[dict]) -> dict[str, int]:
    # Deterministic: sort distinct keys, number 1..k. Same set of voiceprints
    # → same Speaker N regardless of who spoke first or which engine ran.
    keys = sorted({_speaker_key(d) for d in identity_segments})
    return {k: i + 1 for i, k in enumerate(keys)}
```

`merge_by_timestamp` and the new `build_resolved_speakers` (below) **both** use `_label_index` so
the keys in `resolved_speakers` are byte-identical to the `seg.speaker` labels on the persisted
`RawSegment`s. `label_for(d)` stays `d["name"] or f"Speaker {index[_speaker_key(d)]}"`.

> **Existing test stays green:** `test_merge_named_and_anonymous` expects
> `["alice@x.com","bob@x.com","Speaker 3"]`. Sorted keys `vp_a<vp_b<vp_c` → `1,2,3`; vp_a/vp_b are
> named, vp_c anonymous → `Speaker 3`. ✅ (Numbering counts **all** distinct voiceprints, named
> included — that's what makes vp_c "Speaker 3", not "Speaker 1".)

### 1.2 New helper: `build_resolved_speakers` (record_routes.py — B owns this file)
```python
def build_resolved_speakers(identity_segments: list[dict]) -> dict[str, dict]:
    """FPM identity segments → {display_label: {voiceprint_id, name, confidence}} per C3.

    Keyed by the SAME display label merge_by_timestamp assigns, so it joins the
    persisted RawSegment.speaker. One entry per distinct speaker key. Picks the
    max-confidence segment per speaker as the representative name/confidence.
    """
    index = _label_index(identity_segments)
    best: dict[str, dict] = {}
    for d in identity_segments:
        key = _speaker_key(d)
        conf = float(d.get("confidence") or 0.0)
        if key not in best or conf > best[key]["_conf"]:
            label = d.get("name") or f"Speaker {index[key]}"
            best[key] = {
                "label": label,
                "voiceprint_id": d.get("voiceprint_id"),
                "name": d.get("name"),          # may be None (anonymous/unknown)
                "confidence": d.get("confidence"),
                "_conf": conf,                  # sort scratch, stripped below
            }
    return {v["label"]: {"voiceprint_id": v["voiceprint_id"], "name": v["name"],
                         "confidence": v["confidence"]} for v in best.values()}
```
C3 freezes the value shape to exactly `{voiceprint_id, name, confidence}` — do **not** add `decision`
or `local_speaker` (engine-private; would leak C1 internals across the repo boundary).

### 1.3 Wire it into `record_meeting`
Replace L229 `session.metadata.resolved_speakers = resolve_speakers(session)` with:
```python
session.metadata.resolved_speakers = build_resolved_speakers(identity)
```
`identity` is already in scope (L195–198). **Do not** also call the cohort `resolve_speakers` here —
different keyspace (see audit §0.3). The cohort resolver stays untouched on the upload/paste
(`upload_routes.py:133`) and canonical-webhook (`transcripts_routes.py:702`) paths.

### 1.4 Read path
`to_transcript` (L288–318) already projects `resolved_speakers[label]["name"]` → `speaker_name`
without rewriting `seg.speaker`. With C3 entries now carrying `name`, this works as-is. B's read-path
work is therefore **a guard test, not a rewrite**: assert the projection holds for a record-shaped
session and that `seg.speaker` / `Signal.said_by` are never mutated. (Optional, low-risk: also expose
`voiceprint_id` on each `to_transcript` segment for the P4 UI — **defer** unless P4 needs it; keeping
the read shape minimal avoids a contract ripple.)

### 1.5 `models.py`
**No structural change.** `resolved_speakers: dict[str, Any]` already accepts C3. Update only the
inline comment at L37–38 to document the C3 value shape (`{voiceprint_id, name, confidence}` for the
record/voiceprint path; `{record_id, name, mock}` remains the legacy cohort shape). Doc-only → zero
runtime/merge risk.

---

## 2. Scope (files)
| File | Change | Risk |
|---|---|---|
| `api/record_routes.py` | Add `_speaker_key`, `_label_index`; refactor `merge_by_timestamp` to use them (deterministic numbering, key by `voiceprint_id`); add `build_resolved_speakers`; swap L229 to call it. **B owns this file — A must stay out (architecture §6).** | Med |
| `api/transcripts_routes.py` | **No code change expected** — `to_transcript` already projects. Add a guard test only. Touch code *only* if a projection gap is found. | Low |
| `transcripts/models.py` | Doc-comment on `resolved_speakers` field (C3 value shape). No structural change. | None |
| `tests/test_record_routes.py` | New unit + integration tests (§4). | — |
| `tests/test_api_transcripts.py` | One read-path projection guard test (§4). | — |

**Explicitly out of scope (do not touch):** `transcripts/identity.py` (cohort resolver stays as-is),
`transcripts/sources.py`, `transcripts/parse.py`, `api/upload_routes.py`, any FPM file, any Alembic
migration.

---

## 3. Things to be careful about

- **Two-keyspace discipline.** `voiceprint_id` lives in `resolved_speakers` metadata; the **display
  label string is the immutable join key** for already-enriched signals (`Signal.said_by`,
  `about_person`). Project names at read time; never rewrite derived blobs or `RawSegment.speaker`.
- **`voiceprint_id` never rides on a segment / `RawSegment`.** It is written straight into
  `resolved_speakers` in `record_routes` from the in-memory `identity` list (audit §0). Anyone who
  tries to thread it through `json.dumps(merged)` → `_parse_upload` will watch it get stripped at
  `sources._normalize_json_segment`.
- **Schema-change blast radius (audited — all safe).** Record meetings now carry
  `{voiceprint_id, name, confidence}` instead of `{record_id, ...}`. Consumers that key on
  `record_id` are all **legacy-cohort-only** and unaffected for record meetings:
  - `can_see` legacy path (`transcripts_routes.py:98`) — record meetings use **workspace mode**
    (`set_workspace(..., visibility="owner-only")`, record_routes L233–238), so `can_user_see` (typed
    columns) runs, never the resolved_speakers record_id branch.
  - `/me/action-items` (L524–575) and `/_cohort/roster` (L578–604) — cohort dashboard surfaces;
    record voiceprint speakers simply won't appear there. **Acceptable for P2; P4/P5 own the
    voiceprint→owner_email dashboard.** Note this limitation in the PR description.
  - `ingest.py` owner-from-first-speaker (L72–80) — only the file-ingest CLI path; record never sets
    that flag. Untouched.
- **Deterministic numbering is what makes replace-safety work** across the live→post swap. Within a
  single post pass it's fully deterministic. Across live (key by `local_speaker`, no minting) vs post
  (key by `voiceprint_id`), `Speaker N` for *unknowns* may differ — **fine**, because post **replaces**
  live wholesale (architecture §10). Document this in the `merge_by_timestamp` docstring so it isn't
  mistaken for a bug.
- **Pure consumer of C2 — degrade gracefully.** If FPM segments lack `voiceprint_id` (older FPM, or
  the live read-only path before mint), `_speaker_key` falls back to `local_speaker`/`"spk"`,
  `voiceprint_id` in the C3 entry is `None`, and numbering still works. **Never crash the upload
  path.** Keep `build_resolved_speakers` total over empty/partial input (empty `identity` → `{}`).
- **`raw_diarization`/`RawSegment` are immutable** — `voiceprint_id` goes in `resolved_speakers`, not
  on the raw segment (`models.py:19–31`). Don't add a field to `RawSegment`.
- **Confidence may be `None`.** `float(d.get("confidence") or 0.0)` for the max-pick scratch; but
  **store the original** (possibly `None`) in the C3 entry — don't coerce stored confidence to 0.0.

---

## 4. Test suite (test-first → green → atomic commit each)

Order matches the build sequence; each step's test is written first and must fail for the right
reason before implementing. One commit per step, test in the same commit.

**Unit — `tests/test_record_routes.py` (extend the existing `# pure merge unit` block):**

1. **`test_merge_preserves_voiceprint_id_in_resolved` (build_resolved_speakers).** Feed `_IDENTITY`
   → assert `build_resolved_speakers(_IDENTITY)` ==
   `{"alice@x.com": {"voiceprint_id":"vp_a","name":"alice@x.com","confidence":...},
   "bob@x.com": {...vp_b...}, "Speaker 3": {"voiceprint_id":"vp_c","name":None,"confidence":...}}`.
   Locks C3 value shape + label join with merge.
2. **`test_deterministic_numbering_independent_of_order`.** Run `merge_by_timestamp` (and
   `build_resolved_speakers`) on `_IDENTITY` and on a **shuffled** copy (reverse the segment order)
   → identical `Speaker N` labels and identical `resolved_speakers` keys. This is the live↔post
   convergence guarantee.
3. **`test_anonymous_only_numbering_stable`.** All `name=None` segments with distinct
   `voiceprint_id`s → `Speaker 1..k` assigned by sorted `voiceprint_id`, stable across two calls.
4. **`test_build_resolved_speakers_graceful_without_voiceprint`.** Segments with `voiceprint_id`
   absent (only `local_speaker`) → no crash, entries carry `voiceprint_id=None`, keyed by
   `local_speaker`-derived `Speaker N`. (C2-degrade guard.)
5. **Keep `test_merge_named_and_anonymous`, `test_merge_no_identity...`, `test_merge_drops_empty_text`
   green unchanged** (regression on the labelling refactor).

**Integration — `tests/test_record_routes.py` (extend `test_record_happy_path...`):**

6. **`test_record_persists_resolved_speakers_c3`.** POST `/record` with stubbed FPM/ASR (existing
   `_enable_record`); load the session; assert
   `session.metadata.resolved_speakers["alice@x.com"]["voiceprint_id"] == "vp_a"`, `["Speaker 3"]
   ["voiceprint_id"] == "vp_c"`, and every entry has exactly the keys `{voiceprint_id, name,
   confidence}`. Also assert `RawSegment.speaker` labels still
   `["alice@x.com","bob@x.com","Speaker 3"]` (unchanged behaviour).

**Read-path — `tests/test_api_transcripts.py`:**

7. **`test_transcript_projects_voiceprint_name_without_rewriting_label`.** Build a session whose
   `resolved_speakers = {"Speaker 3": {"voiceprint_id":"vp_c","name":"Carla","confidence":0.9}}` and
   a `RawSegment(speaker="Speaker 3", ...)`; call `to_transcript` → segment has
   `speaker == "Speaker 3"` (immutable join key) **and** `speaker_name == "Carla"` (projection).
   Add a paired assertion that a `Signal(said_by=["Speaker 3"])` is **not** mutated by any read-path
   call (`to_view`).

**Regression (must stay green, run explicitly in the DoD gate):**

8. `tests/test_upload_routes.py`, `tests/test_identity.py` (cohort resolver unchanged),
   `tests/test_api_transcripts.py` (existing `to_transcript`/card tests), `tests/test_sources.py`,
   `tests/test_record_routes.py` route tests (auth/404/503/empty/idempotency).

Run gate: `pytest tests/test_record_routes.py tests/test_api_transcripts.py tests/test_upload_routes.py
tests/test_identity.py tests/test_sources.py -q`.

---

## 5. Merge-conflict & parallelization discipline (architecture §6)
- **B owns `api/record_routes.py`.** Branch A (FPM P0) **must not** edit it. B touches **no FPM
  code** → `B ⟂ C ≈ 100%`. B's only Conclave files (`record_routes.py`, two test files, a doc
  comment in `models.py`/`transcripts_routes.py`) don't overlap A's FPM scope.
- **Merge order:** B first (it's the critical-path foundation; A & C merge after, integration-tested
  jointly). Land B before P4/P5 start so the handshake/redaction work has the stable `voiceprint_id`
  key to build on.
- **Contract freeze:** B is a *pure consumer* of C2 and a *producer* of C3. Do not let either drift
  while B is in flight; if FPM's C2 line shape changes, that's an A-side coordination, not a B edit.
- **Atomic commits:** (1) labelling refactor + unit tests; (2) `build_resolved_speakers` + unit
  tests; (3) record-route wiring + integration test; (4) read-path guard test (+ doc comments).
  Four commits, each green.

---

## 6. Definition of done
- `voiceprint_id` persisted per C3 (`{voiceprint_id, name, confidence}`) in `resolved_speakers` for
  every recorded meeting, written directly from the FPM identity segments (not via `_parse_upload`).
- `Speaker N` numbering deterministic by sorted speaker key (voiceprint_id-preferred) — identical
  across reordered input and across re-runs.
- Display name projected at read time (`to_transcript.speaker_name`); `RawSegment.speaker` and
  `Signal.said_by` never rewritten.
- All new tests green; upload/paste, canonical-webhook, cohort-identity, and existing record-route
  regressions green; **no FPM changes; no SQL migration.**
- PR description notes the one accepted limitation: record-meeting voiceprint speakers don't surface
  in the legacy cohort `/me/action-items` / `/_cohort/roster` (those key on `record_id`; the
  voiceprint→owner_email dashboard is P4/P5).

---

## 7. Contract compliance & FPM-branch sync (verified 2026-06-13)

Checked B against all four ARCHITECTURE.md contracts and against the FPM-side branches A (P0
DiariZen engine) and C (P1 read-only + P3 confidence gate). B breaks **none** of them and stays in
sync **iff** the one coordination point below holds.

### C1 — `StreamingDiarizer` engine seam (FPM-internal)
B never touches it. B's only contact with it is *transitive*: `local_speaker` (the one engine-private
field C1 emits) is used **only as a fallback numbering key** when `voiceprint_id` is absent, and is
**never written into `resolved_speakers`** (C3 entries carry no `local_speaker`). So swapping engines
(A's DiariZen, a future TS-VAD) can never invalidate B's output — exactly the firewall the seam
promises. ✅

### C2 — `/v1/diarize` NDJSON shape (B is the consumer)
- B reads exactly the C2 fields `{voiceprint_id, name, confidence}` (+ `start/end` for overlap,
  `local_speaker` as fallback key). It **adds, reorders, or drops nothing** in the stream → any
  live-path change by A/C that "preserves this shape" stays compatible. ✅
- **THE ONE SYNC RISK (coordination, not a conflict):** `_fpm_diarize` prefers the final
  `{"type":"transcript","segments":[...]}` message over the streamed lines. B's correctness depends
  on **those final segments carrying `voiceprint_id`/`name`/`confidence`**, not a reduced
  display-only `{start,end,text,local_speaker}` shape. C2's wording ("seal-corrected"; "Conclave
  consumes `voiceprint_id`") *implies* the final view is the same `_segment_dict` shape, but FPM
  source isn't in this repo to confirm. **Mitigation (Commit 5, in B's owned file):** `_fpm_diarize`
  is hardened so that if a final segment lacks `voiceprint_id`, identity is back-filled from the
  best-overlapping **streamed** line (which C2 *guarantees* carries it). Net: B is correct whether
  FPM's final view carries identity or not — the cross-repo ambiguity is closed from the Conclave
  side, no FPM change required. Flag to A/C owners as a confirm-only item.
- **`voiceprint_id=None` is a valid C2 value** (P3 gates minting → permanently-unnameable speakers).
  B handles it: falls back to `local_speaker` for the numbering key (so two distinct unnameable
  speakers don't collapse) and stores `voiceprint_id=None` in the C3 entry — which is precisely the
  signal P4/P5 UI reads as "don't offer 'name this speaker'." ✅

### C3 — `resolved_speakers` schema (B is the producer)
- B emits exactly `resolved_speakers[label] = {voiceprint_id, name, confidence}` — the frozen shape,
  no extra keys (no `decision`, no `local_speaker`). ✅
- **Immutable join key honoured:** the `label` string is `name or "Speaker N"`, computed by the same
  function for both the persisted `RawSegment.speaker` and the `resolved_speakers` key, so they join
  byte-for-byte. B never rewrites `RawSegment.speaker`, `Signal.said_by`, or `about_person`; the name
  is projected at read time (`to_transcript.speaker_name`). A later name re-resolve (P4/P5) updates
  `…[label]["name"]` only, never the label. ✅
- **"Name is always a projection" (architecture §2):** B stores `name` as a *cached* projection of
  the ingest-time `voiceprint_id`. The source of truth stays `voiceprint_id → owner_email → name`,
  realized by FPM at P4/P5; B's stored name is overwritten on re-resolve. Storing it now is the C3
  cache, not a competing truth. ✅
- **No SQL migration** (`resolved_speakers` is already `dict[str, Any]`), so B cannot collide with any
  Alembic-owning branch. ✅

### C4 — propose/confirm/deny + consent-query (P4/P5)
Not implemented by B, and B doesn't pre-empt it: by persisting the stable `voiceprint_id` key, B is
the thing that *makes C4 possible*. P4 walks `resolved_speakers`, matches on `voiceprint_id`, and
re-projects names through the consent gate. ✅

### Sync with the FPM branches if both follow plan
- **B ⟂ C ≈ 100%** — disjoint repos; B touches no FPM file. C's P1 (live read-only, mints nothing)
  and P3 (`voiceprint_id=None` unnameables) produce C2 shapes B already handles (see above).
- **B ⟂ A** — A ports the DiariZen engine behind C1 and adds a factory branch in FPM `main.py`; B
  consumes whatever C2 the post instance emits, independent of which engine produced it. A must stay
  out of `record_routes.py` (it's FPM-only, so this is automatic). No shared file.
- **Merge order B → A & C → P4/P5** is preserved; nothing in B's implementation assumes A or C has
  landed (graceful C2-degrade), so B can merge first on the critical path.

**Conclusion:** following this plan, B is contract-clean and stays in lock-step with A and C. The
single confirm-item (final-message identity fields) is defended from B's side, so even a stricter
reading of C2 cannot desync B.

## 8. Commit plan (atomic, test-gated — advance only when the prior gate is green)

| # | Commit | Files | Test gate (must pass before next) |
|---|---|---|---|
| 1 | docs: contract-compliance + commit plan | `docs/plans/branch-B-persistence.md` | — (doc only) |
| 2 | `merge_by_timestamp` deterministic, voiceprint-keyed numbering | `api/record_routes.py` + `tests/test_record_routes.py` | merge unit tests (existing 3 + determinism + anon-stable) |
| 3 | `build_resolved_speakers` (C3 producer) | `api/record_routes.py` + tests | C3-shape + graceful-degrade + max-confidence unit tests |
| 4 | wire into `record_meeting`; persist C3 | `api/record_routes.py` + tests | full `tests/test_record_routes.py` |
| 5 | harden `_fpm_diarize` to guarantee `voiceprint_id` (back-fill final from streamed) | `api/record_routes.py` + tests | NDJSON-parse unit test + full record file |
| 6 | read-path guard test + C3 doc comment | `tests/test_api_transcripts.py`, `transcripts/models.py` | full `tests/test_api_transcripts.py` |

Final gate (DoD): `pytest tests/test_record_routes.py tests/test_api_transcripts.py
tests/test_upload_routes.py tests/test_identity.py tests/test_sources.py -q` all green.
