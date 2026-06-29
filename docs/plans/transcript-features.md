# Transcript features — end-to-end (capture → diarization → identity → editor → insights)

> What Conclave does with a transcript, from the moment audio is captured to the corrected,
> human-approved, speaker-attributed transcript that drives summaries, insights, and the knowledge
> base. Covers the diart/DiariZen diarization flow, VFTE voice identity, the v2 correction layer +
> inline editor (NER pre-typing, vocab autocomplete, entity/speaker tagging), and the
> edit → approve → regenerate loop (including re-editing after approval).
>
> Lives on `main`. Companion docs: `transcript-refine.md` (original design), `inline-editor-buildout.md`
> (#6/#7/cutover build spec, on the feature worktree), `transcript-refine-issues.md` (parked items),
> `contract-C4.md` (VFTE consent contract). The top-level `README.md` covers the 3-repo system + the
> in-person pipeline at a higher level.

---

## 0. The layered model (read this first)

A meeting becomes **four stacked layers**, each immutable below the next:

1. **`raw_diarization`** — the immutable, write-once transcript: `[{speaker, text, start, end}]`. The
   *only* sanctioned overwrite is the DiariZen authoritative re-diarization at finalize.
2. **`resolved_speakers`** — a display/identity overlay (`label → {voiceprint_id, name}`) from VFTE.
   Never rewrites the raw labels; it *resolves* them at read time.
3. **`transcript_v2`** — the human **correction layer** (`draft` → `approved`): token-level edits,
   entity annotations, and per-segment `speaker_name`. Raw stays untouched; corrections live here.
4. **`derived`** + **KB** — the summary, signals (action items / open questions / insights), and the
   extracted entity/obligation graph. Built from the **approved v2** (falls back to raw if unapproved).

**Operator-blind:** every LLM call is at *ingest* inside the TEE; the read path is local SQL + embeddings.

---

## 1. Capture & ingest — three paths into a transcript

| Path | How audio arrives | Diarization | ASR |
|---|---|---|---|
| **In-person walk-up** | Browser mic → WS to the capture diarization service (`/v1/inperson/stream`) | **diart** (live, CPU) | **NEAR Whisper** per span |
| **Online Google Meet** | A capture bot joins (warmed profile) + streams | structural speaker labels (live) → **DiariZen** (post) | **NEAR Whisper** |
| **Upload** | Pasted text / file (`POST /api/workspaces/{ws}/transcripts`) | none (already segmented) | none |

**In-person streaming flow (the flagship):**
```
browser mic ──► capture /v1/inperson/stream
                 ├─ diart live-diarizes (CPU) → speaker spans
                 └─ each finalized span → NEAR Whisper ASR
                          │
                          ▼
                 Redis `transcription_segments`  ──►  Conclave consumer
                 (connectors/capture/consumer.py)     → `live_segments` buffer
                          │                            → live SSE preview (/api/meetings/{id}/live)
                  on STOP │
                          ▼
   capture POSTs the recording (/api/capture/audio-chunk)
   + fires the finalize webhook (/api/webhooks/capture/meeting-completed)
```

The online-bot path is the same shape minus the mic (the bot streams `transcription_segments` live,
then the webhook finalizes from the buffered segments).

---

## 2. Finalize — the background pipeline

On `meeting-completed` (`api/webhooks_capture.py`), Conclave spawns a **non-blocking background task**
`_identify_then_enrich()` (`asyncio.create_task`):

```
1. materialize raw_diarization from live_segments        (write-once, idempotent)
2. identify_meeting(...)        ── connectors/capture/identify.py ──
     ├─ DiariZen authoritative re-diarize → OVERWRITES raw_diarization   (if CONCLAVE_DIARIZE_URL set)
     │     else → use capture's own diart spans (no overwrite)
     └─ VFTE /v1/identify-spans  → voiceprints per speaker → resolved_speakers
3. _enrich_in_background(...)   ── api/transcripts_routes.py ──
     ├─ create_v2_draft(...)    → the editable correction layer (candidate detection runs ONCE here)
     └─ enrich_session(...)     → summary + signals via the LLM (RedPill/Gemma)
```

**Identity-before-enrich** ordering matters: `resolved_speakers` carries voiceprint_ids before
enrichment + the read path. **The v2 draft is created AFTER `identify_meeting`** — so the editor (which
needs the draft) can never open on the diart preview; it only opens once the authoritative transcript
is in place.

---

## 3. Diarization — diart (live) + DiariZen (authoritative), with graceful fallback

- **diart** — online/streaming, **CPU**-pinned. Drives the live preview (`[speaker] text` as the
  meeting happens). Engine lives in the capture diarization service.
- **DiariZen** — post-processing, **GPU**-intended, more accurate. At finalize it re-diarizes the whole
  recording **authoritatively** and **overwrites `raw_diarization`** (the one sanctioned override), then
  every ASR segment is re-attributed to DiariZen's speaker.
- **Graceful fallback (`connectors/capture/identify.py`):**
  - `CONCLAVE_DIARIZE_URL` **unset** → finalize keeps capture's **diart spans** (`src="diart(raw_diarization)"`).
  - DiariZen call **fails** → `diarize_client` logs + returns `[]`; the whole identify is wrapped
    "never block finalize" → degrades to diart labels. **A DiariZen failure never crashes.**
  - The diarization service is **single-engine per deployment** (`CAPTURE_DIARIZER=diart|diarizen|remote`);
    a missing engine surfaces as a clean `DiarizerUnavailable` (503), not a 500.
- **CPU-only mode:** DiariZen is impractical on CPU (RAM/OOM), so the local/CPU path runs **diart-only**
  and the diart transcript is authoritative.

---

## 4. Voice identity — VFTE / FPM

Identity is a **separate service** (VFTE, dir `FPM/`); diarization was stripped out of it.

- **Mint/recognize** — `POST /v1/identify-spans` re-embeds each diarized span with **CAM++**, matches the
  workspace voiceprint store, and (with `tag=offline`) **mints a voiceprint** for unknown speakers →
  `resolved_speakers[label].voiceprint_id`. A later meeting **recognizes** the same speaker with no re-tag.
- **Consent-gated naming** — `POST /v1/propose` binds a `voiceprint_id` to a (name, email). It
  **auto-confirms** a self-tag (`proposed_by == proposed_email`) or when the dev flag
  `FPM_CONSENT_AUTOCONFIRM` is on; otherwise it's **pending** until the person confirms on their consent
  dashboard (a notify email fires when SMTP is configured). Read side: `GET /v1/consent/resolve/...`.
- **Conclave side** — `record_routes.tag_speaker` maps `resolved_speakers[label].voiceprint_id` →
  `propose_binding`; on confirm, `reresolve_voiceprint` flips the name across the workspace's transcripts.
- **Known limitation (parked):** a speaker whose total speech is under VFTE's `MIN_SEGMENT_SEC` (1.0s)
  gets **no voiceprint**, so `tag-speaker` 404s. The intended fix decouples *text attribution*
  (name+email, always allowed, email-confirmed) from the *voiceprint* anchor — see
  `transcript-refine-issues.md`.

---

## 5. The v2 correction layer

`transcript_v2` (migration `0018`): `status` (`draft`→`approved`), `doc_json` holding
`segments[{segment_id, speaker_label, speaker_name, tokens[]}]` + `annotations[]` + `insights_stale` +
`approved_at`. Store seams (`transcripts/store.py`): `create_v2_draft`, `load_v2`, `edit_token`,
`add_annotation`, `assign_speaker`, `approve_v2`, `v2_segments_or_raw`, `clear_insights_stale`.

- Raw is never mutated by edits; all corrections land on v2.
- `v2_segments_or_raw(session_id)` returns the **approved** v2 (corrected tokens + confirmed speakers)
  when present, else raw — used by both the KB build *and* the read path (so viewers see the corrected
  version once approved).

---

## 6. The refine editor — inline on the meeting page

Since the **cutover**, the editor **replaces** the read-only transcript on `/meeting/[id]` (the
standalone `/refine` route was removed). Role/state behavior:

- **Owner, draft ready** → the inline token editor (`RefineEditor`) + actions (`RefineActions`).
- **Owner, draft still preparing** (post-recording, draft 404) → read-only **live transcript** +
  "post-processing" banner; auto-swaps to the editor when the draft is ready (so you never edit a
  transcript DiariZen is about to overwrite).
- **Viewer / shared recipient** → read-only transcript showing the **approved v2 (else raw)**.

**Editor capabilities (per token / per segment):**
- **Edit any word** — click → inline input → Enter/blur commits (`edit_token`).
- **Vocab autocomplete (#6)** — typing in the edit input shows a per-user **dictionary** dropdown
  (`vocabSuggestions`); click to fill.
- **Tag an entity** — tag any word with a type (`person · project · tech · affiliation · topic`)
  (`tag-entity`); writes a `source="user"`, `state="known"` annotation.
- **Assign / name a speaker** — a plain text label, OR the **VFTE name+email tag form** (consent flow,
  same as the transcript page) when the meeting has voiceprints; suggestion chips from warm voiceprints
  + invitees.
- **Token tints** — `known` (green) / `candidate` (blue) / `oov` (amber).
- **Write-error surfacing** — failed writes show a banner + re-sync from the server (no silent
  optimistic-only state).

---

## 7. Candidate detection & word-typing (#7)

`transcripts/candidate.py`, spaCy `en_core_web_sm` (CPU, TEE-friendly), run **once** at draft time.

- **OOV detection** — a token with `wordfreq.zipf_frequency` below the OOV cutoff (novel terms like
  "Recato", "DStack") → `state="oov"` (amber). Common words are not flagged (OOV-only — the noun-chunk
  over-tagging was dropped).
- **POS promotion gate** — `classify_correction(token)`: `NOUN`/`PROPN`/OOV → `"promote"` (graph-worthy),
  grammar/function words → `"text"`. This gate decides whether a correction grows the vocab.
- **NER pre-typing** — spaCy **NER** (`doc.ents` / `ent.label_`) assigns an **entity type** to candidate
  spans off the same spaCy doc. Mapping: `PERSON→person`, `ORG→affiliation`, `PRODUCT→tech`,
  `WORK_OF_ART/EVENT/LAW→topic`. **Noise labels are deliberately NOT mapped** — `LANGUAGE` (e.g.
  "Arabic"), `NORP` (nationalities/groups, e.g. "American"), and geographic `GPE/LOC/FAC` (spaCy tags
  "Hindi" as GPE) — because they surface as nonsensical entity tags in meeting transcripts. NER refines
  *type* only; provenance stays `nlp`; it does not change the promotion rule. The **authoritative** LLM
  entity extraction stays **post-approval** (the KB build) — no in-editor LLM.

---

## 8. The per-user vocabulary flywheel

`transcripts/vocab.py` + `transcripts/ground_truth.py` + the `vocab` table (`0018`).

- Every confirmed **tag** writes `vocab.put(user, surface, type, provenance="user")`; every **correction**
  that the POS/OOV gate promotes writes `provenance="correction"`; NLP candidates are `provenance="nlp"`.
  Precedence on the same key: `user` > `correction` > `nlp`.
- The loop: corrections → per-user vocab grows → better candidate detection/suggestions → fewer
  corrections (toward "graduation"). Per-user isolated; it's also the substrate Part 2 (graph synthesis)
  reads as a high-precision prior.

---

## 9. Edit → approve → regenerate (and re-edit)

- **Edits mark `insights_stale`** — the on-screen insights (built before correction) are flagged out of
  date. No live/on-edit recompute (a deliberate latency/cost decision).
- **Approve & build** (`approve_v2` → `_post_approve_build`):
  - `_rederive_insights_from_v2` re-runs `enrich_session` on the **corrected v2** segments (not raw) →
    new summary + signals → `clear_insights_stale`.
  - `_build_kb` extracts entities/obligations from the approved v2.
- **"Updating insights" indicator** — after approve, the meeting page shows an *Updating insights…* sign
  and polls the draft's `insights_stale` until the background re-derive lands, then swaps in the fresh
  signals.
- **Re-editable after approval (Q3)** — editing an **approved** transcript **re-opens it to `draft`**
  (`store` flips `status=draft`, clears `approved_at`, sets `insights_stale`) instead of rejecting the
  edit; you then **re-approve** to re-derive. *(This intentionally reverses the original V2-3
  "frozen after approve" contract.)* Only a real text change re-opens — a stray click that doesn't
  change a token does not.
- **Idempotent** — re-approving an unchanged, already-approved transcript rebuilds nothing.

---

## 10. Trust & automation

`transcripts/trust.py` + the refine sweep (`infra/scheduler.py`):

- **Correction-rate graduation** — users graduate `gated → auto` as their correction rate drops; the
  gate reads the trust state.
- **Auto-approval timeout sweep** — graduated (auto) users' draft transcripts auto-approve after a
  timeout window (default ~8h); gated users are untouched.
- **Post-meeting review reminder** — a one-time reminder (~1h post-meeting) for both user types.

---

## 11. Configuration reference (the flags that drive the flow)

| Flag | Effect |
|---|---|
| `CONCLAVE_INPERSON_VIA_CAPTURE` | finalize uses capture's spans + VFTE `identify-spans` (vs the legacy `/v1/diarize`) |
| `CONCLAVE_DIARIZE_URL` | set → DiariZen authoritative post-pass; unset → diart-only |
| `CONCLAVE_FPM_BASE_URL` / `_API_TOKEN` / `_WORKSPACE` | VFTE identity wiring |
| `CONCLAVE_LLM_BACKEND` (`redpill`/`nearai`/`ollama`) + `CONCLAVE_REDPILL_MODEL` | enrichment LLM (e.g. `google/gemma-3-27b-it`) |
| `CONCLAVE_SKIP_ENRICH` | skip the LLM (no summary/insights) — local/token-saving |
| `REDIS_URL` | enables the capture segment-stream consumer (live ingest) |
| `CAPTURE_DIARIZER` (`diart`/`diarizen`/`remote`) | which diarization engine the capture service runs |
| `FPM_CONSENT_AUTOCONFIRM` | dev: auto-confirm consent proposals (no email round-trip) |

---

## 12. Known limitations / parked

- **Short-clip speaker tagging** — no voiceprint under `MIN_SEGMENT_SEC` → `tag-speaker` 404s; the
  attribution-vs-voiceprint split is designed but unbuilt (`transcript-refine-issues.md`).
- **Standalone-tag regen (#13)** — regen fires on full *approve*, not yet on a *single confirmed tag*;
  the shared regen primitive now exists for #13 to build on.
- **NLP deps in the image** — `spacy` + `en_core_web_sm` + `wordfreq` ship in `requirements.txt` so
  candidate detection/NER works inside the TEE image (CPU-friendly).
