# Ground-truth yaml conventions — Phase 3.5.0 (C2)

> Authority for how the three `.expected.yaml` files are hand-coded.
> Phase 3.5.0 C4 folds the bake-off + locked-prompt decisions on top of
> this into `transcripts/EVAL.md`; this file stays as the *schema* +
> *labelling rules* the eval set commits to.
>
> Captured 2026-06-03. Solo founder, no two-annotator agreement available.

---

## File contract

Each `.expected.yaml` is a hand-coded approximation of what a perfect
extractor would emit for one transcript. C3 measures both prompt shapes
(Q1 bake-off) against these files; C13 regression-tests the locked
prompt against them; C24 uses the `queries:` section for NDCG@10
(Q3 reranker decision).

Top-level keys (all required):

```yaml
transcript: "<exact filename in this directory>.txt"
shape:      "<one of: project-intro | workshop | one-on-one | ops-sync | mixed-*>"
notes:      "free-form labeller notes; cohort, register, expected density"
entities:   [...]   # may be empty list
obligations: [...]  # may be empty list
queries:    [...]   # may be empty list
```

A yaml passes the C2 schema test iff:
1. `transcript:` matches a file present in this directory.
2. `shape:` is a non-empty string.
3. `entities`, `obligations`, `queries` are lists (possibly empty).
4. Each list-entry conforms to the row schemas below.

---

## Turn-id convention

A **turn = one parsed Otter segment** (one `Speaker  M:SS\n<body>` block).
Turn-ids are **0-indexed positions in `Session.raw_diarization`** after
`transcripts.sources.read_file` parses the transcript, which is the same
ordering the chunker (C6) and storage layer use. This makes turn-ids
stable across the eval pipeline.

To enumerate turn-ids for a transcript:

```bash
python3 -c "
from transcripts.sources import read_file
ni = read_file('tests/fixtures/transcripts/<file>.txt')
for i, s in enumerate(ni.segments):
    body = (s['text'] or '').replace(chr(10), ' ')[:60]
    print(f'{i:3d}  {s[\"start\"]:>7.1f}  {s[\"speaker\"]:<22}  {body}')
"
```

If a transcript's parsing later changes (e.g. the Otter header regex is
extended), turn-ids in these yamls must be migrated — there is no
back-compat layer.

---

## `entities[]` row schema

```yaml
- type: person | project | topic | company | tool
  canonical_name: "Albiona Hoti"
  raw_mentions: ["Albiona Hoti", "Albiona"]      # surface forms as seen
  turn_ids: [11, 19, 21, 24, 26, 28, 30]         # turns the entity is referenced in
```

### Naming rules

- **person** — full name when you (the labeller) know it. Surface form
  in `raw_mentions[]`. Verbatim transcription artifacts (`shawmakesmagic`,
  `Hunter (tinycloud)`) belong in `raw_mentions`, not `canonical_name`.
  When you genuinely don't know the full name, use the transcript label
  verbatim as `canonical_name`.
- **project** — what the speaker calls it. `Elocute`, `Wikigen`, `Conclave`,
  `Smithers`, `Router`. Match capitalization to the project's own usage,
  not the transcription's whim.
- **topic** — concept or technique the conversation is *about*, distinct
  from a project. `MCP`, `TEE`, `articulation practice`, `bi-temporal facts`.
  Reserve for things that recur or get defined; don't entity-ify every
  noun.
- **company** — `Tools Masters Club`, `Anthropic`, `Flashbots`.
- **tool** — concrete software/hardware product. `Cloud Code`, `Codex`,
  `Phala Cloud`, `Otter`. Border with `project` is fuzzy; lean toward
  `tool` if the speaker is *using* it, `project` if they're *building* it.

### Quoting `raw_mentions`

Include every distinct surface form for the entity that you can find,
ordered by first appearance. Plurals and possessives stay verbatim
(`Albiona's`, `Elocute's`). Spelling errors in the transcript stay
verbatim (`Howell Base Ace`).

### Granularity

Conservative: when in doubt, **don't** create a new entity. Q5 ER will
get tested by genuine ambiguous cases (different surface forms for the
same canonical), not by overzealous splitting.

---

## `obligations[]` row schema (single table, Q2)

```yaml
- type: action | decision | commitment | open_question | blocker
  description: "Albiona will integrate MCP into Elocute so users can connect via Claude/Cursor."
  source_quote: "I will definitely do it right away, because I can get immediately people more like chatting to the whole LLMs."
  turn_ids: [40]
  owner_raw_text: "Albiona Hoti"     # null when unowned
  due_date_raw: null                 # verbatim transcript text or null
  status_inferred: open              # open | resolved | unclear
```

### Type definitions (Q2 enum)

- **action** — a thing someone said they will do. Future-tense,
  speaker-attributable, concrete enough to verify.
- **decision** — a choice made, ideally with rationale. Past-tense
  ("we decided to ship without reranker") or settled-present ("the
  plan is to monetize via a paywall on the next version").
- **commitment** — a stated promise of value-exchange, often
  conditional. "I would pay for X if Y" / "I'll send you the link
  tomorrow". Distinct from action in that it implies obligation to
  another party. Border with action is fuzzy — when uncertain, label
  as `action` (recoverable downstream) rather than guessing.
- **open_question** — a question raised that did not get a definitive
  answer in the transcript. Includes the speaker's own admitted
  uncertainty ("I don't know how to enforce discipline once I've
  decided").
- **blocker** — something explicitly named as blocking progress.
  Includes meta-blockers (tooling, time, AV setup).

### `source_quote` rules

- **Lightly normalized.** Strip filler (`um`, `uh`, dangling `like`,
  trailing `you know`). Fix obvious auto-transcription word-substitutions
  when the meaning is unambiguous (`keeping a 5.5` → `getting a 5.5`).
  Never paraphrase or restructure.
- Quote one sentence, or two if needed for grounding. Don't fold an
  entire turn into a single quote.
- Speaker-prefix is **not** included; the speaker comes from
  `owner_raw_text` (or the turn's parsed speaker, if you check).
- Apostrophes and punctuation as the transcript shows them.

### `owner_raw_text`

The surface form for who *carries* the obligation, not who said the
sentence. For an action `Albiona will do X`, `owner_raw_text = "Albiona Hoti"`.
For an obligation `we should do X` with no clear ownership, set to
`null`. The Q5 ER pass downstream resolves this to an entity id;
hand-coded ground truth stores the raw text so we measure ER
end-to-end, not just extraction.

### `status_inferred`

- `open` — the obligation is live as of the transcript's end.
- `resolved` — the transcript itself shows it being satisfied.
- `unclear` — explicitly when the transcript leaves the state
  ambiguous. Don't default to this; use only when the conversation
  genuinely doesn't say.

### Redaction

**No redaction** in source_quotes or raw_mentions. The three transcripts
in this directory are cohort content (semi-public among program members)
and aren't sensitive the way external user interviews would be. If a
future transcript ever needs redaction, do it before adding it to this
directory — these yamls go into git verbatim.

---

## `queries[]` row schema

```yaml
- q: "What is Albiona's main bottleneck for Elocute?"
  intent: factoid | aggregate | relational | temporal
  relevant_turn_ids: [24, 51]
```

### Intent taxonomy

- **factoid** — single fact, single source. "Who's flying in from
  England?" / "What model does the bakeoff use?"
- **aggregate** — sums or sets across the transcript. "What feature
  requests did LSDan make?" / "Which projects mentioned MCP?"
- **relational** — connects two or more entities. "What did Albiona
  and LSDan discuss about monetization?" / "How does Wikigen relate to
  Mithril Biosciences?"
- **temporal** — about ordering or recency. "What did Albiona decide
  to do next after Elocute?" / "Which obligation came up first?"

### `relevant_turn_ids`

Turn-ids that contain the answer or strongly support it. Granularity
**inclusive of any turn that materially contributes to the answer**,
not just the single turn that names it. This matches how the C24
chunked retrieval will evaluate.

### Coverage

5–10 queries per transcript. Aim for at least one query of each
intent if the transcript supports it. Don't manufacture queries the
transcript can't actually answer.

---

## When a transcript label is wrong

If hand-coding reveals the `shape:` you (or C1) assigned doesn't match
the transcript's actual register, **update `shape:` and add a one-line
note in `notes:`** — don't force the data to match the label. The eval
set's value is in its honesty.

Same applies to obligation type labels: if you can't decide between
`action` and `commitment`, prefer `action` and note the ambiguity in
the `description:`. The bake-off will tell us whether type-discriminating
prompts are even worth the cost (Q1).
