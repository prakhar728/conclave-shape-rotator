# Labeller instructions

You are labelling one meeting transcript by writing one YAML file.
Read only the transcript file named in §Task. Do not read any other
`.expected.yaml` in this directory and do not look at any documentation
beyond this file. Output only the YAML; no commentary.

## YAML structure

Write the file at the path given in §Task. Top-level keys, in this order:

```yaml
transcript: "<exact transcript filename, with extension>"
shape: "<one short hyphenated label characterizing the meeting's register>"
notes: |
  <one short paragraph of free-form characterization>
entities: [...]
obligations: [...]
queries: [...]
```

All six keys are required. `entities`, `obligations`, `queries` are
lists; they may be non-empty but cannot be omitted.

## Turn-ids

A "turn" is one parsed segment of the transcript. To get the
0-indexed turn-id map for a transcript, run:

```bash
python3 -c "
from transcripts.sources import read_file
ni = read_file('tests/fixtures/transcripts/<FILE>.txt')
for i, s in enumerate(ni.segments):
    body = (s['text'] or '').replace(chr(10), ' ')[:60]
    print(f'{i:3d}  {s[\"start\"]:>7.1f}  {s[\"speaker\"]:<22}  {body}')
"
```

Every `turn_ids` or `relevant_turn_ids` value must be a list of
non-negative integers strictly less than the total number of segments
that command prints for the transcript. Use this command before
finalizing the YAML.

## `entities[]` row

```yaml
- type: <person | project | topic | company | tool>
  canonical_name: "<string>"
  raw_mentions: ["<surface form 1>", "<surface form 2>"]
  turn_ids: [<int>, <int>, ...]
```

- `canonical_name` is a non-empty string.
- `raw_mentions` is a non-empty list of strings; include every distinct
  surface form for this entity that appears in the transcript.
- `turn_ids` is the list of turns where the entity is referenced.

## `obligations[]` row

```yaml
- type: <action | decision | commitment | open_question | blocker>
  description: "<one sentence describing the obligation>"
  source_quote: "<verbatim or lightly-normalized quote from the transcript>"
  turn_ids: [<int>, ...]
  owner_raw_text: "<who carries the obligation, or null>"
  due_date_raw: "<verbatim date text or null>"
  status_inferred: <open | resolved | unclear>
```

- All fields required. `owner_raw_text` and `due_date_raw` are nullable
  (use the literal value `null`); the other string fields must be
  non-empty.
- `turn_ids` is non-empty.

## `queries[]` row

```yaml
- q: "<a question someone might want to search the transcript for>"
  intent: <factoid | aggregate | relational | temporal>
  relevant_turn_ids: [<int>, ...]
```

- Produce 5–10 queries per transcript.
- `relevant_turn_ids` is non-empty and lists every turn that materially
  contributes to answering the question.

## Output constraints

- Write only the YAML file. No prose, no commentary, no surrounding
  markdown.
- Every list entry must conform exactly to the row schema above.
  Extra keys are not permitted.
- The YAML must be parseable by PyYAML 6.x in safe mode.

## Task

Produce the file at `tests/fixtures/transcripts/<SLUG>.expected.yaml`
for the transcript at `tests/fixtures/transcripts/<TRANSCRIPT FILENAME>`.
