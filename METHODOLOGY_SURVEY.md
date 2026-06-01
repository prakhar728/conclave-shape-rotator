# Methodology Survey — Knowledge Base Construction over Meeting Transcripts

> **Purpose:** the literature and methodology research that informs the architecture
> decisions for Phase 1+ of the transcript intelligence layer. Five parallel deep
> surveys (chunking, KG construction, hybrid retrieval, meeting NLP, agent memory)
> consolidated into one reference, plus a cross-cutting synthesis with what we're
> going with, what we're holding as fallbacks, and what's still open.
>
> **Date:** 2026-05-28. **Branch:** `transcripts-phase1`.
> **Read order:** §1 (decisions matrix) → §2 (open tensions) → §3 (proposed next
> experiments). The five survey sections (§4–§8) are reference for when a decision
> needs to be revisited. §9 is the unified picture that emerges.
>
> Companion to `BUILD_PLAN.md` (strategy) and `IMPLEMENTATION_PLAN.md` (execution).
> This is the *research* layer — what the field knows that informs both.

---

## 1. Decisions matrix — what we're going with, what's the fallback

Each row = an architectural decision. "Primary" = what to build now. "Fallback" =
what we swap to if Primary fails an explicit trigger. "Status" = how settled the
decision is (convergence across surveys vs. genuine open call).

| # | Decision area | Primary (going with) | Fallback (if Primary fails) | Switch trigger | Status |
|---|---|---|---|---|---|
| D1 | Chunking strategy | Turn-aware chunking, never split mid-turn, pack to `min(model_ctx × 0.4, 6k tokens)`, 1-2 turn overlap; per-chunk LLM-generated context header (Anthropic Contextual Retrieval) | RAPTOR-style hierarchical summary tree | per-meeting extraction good but cross-meeting answers shallow at >50 transcripts | **settled** (matches commit `d981345`) |
| D2 | Oversized-turn fallback | Recursive sentence-boundary split within turn, with overlap | Semantic chunking inside the turn | recursive split corrupts continuity | **settled** |
| D3 | Map-reduce vs single-pass | Single-pass when transcript fits chunk budget; map-reduce only when N > 1 | Bounded hierarchical reduce when partials exceed K | reduce-step degradation observed on >K=8 partials | **settled** |
| D4 | KB unit of extraction | Schema-guided typed entities + typed facts (Itext2KG-style — Pydantic schema in prompt) | nano-graphrag-style open extraction (no schema) | schema-constrained extraction misses >20% of human-judged useful edges | **settled** (convergence: Agents 2 & 4) |
| D5 | Storage substrate | Stay SQLite. Add `sqlite-vec` (embeddings) and FTS5 (lexical) — same `.sqlite` file as relational | Lance DB or Chroma embedded | sqlite-vec ANN quality insufficient at >100k vectors (not our problem at our scale) | **settled** (convergence: Agents 2 & 3) |
| D6 | Graph storage | SQL edge tables (`entities`, `entity_mentions`, `facts`) — NOT Neo4j | Neo4j / Memgraph | multi-hop queries become Cypher-shaped and SQL recursive CTE is too painful | **settled** |
| D7 | Retrieval pattern | BM25 (FTS5) + dense cosine (sqlite-vec), fused via Reciprocal Rank Fusion (k=60) | Add BGE-reranker cross-encoder on top-50 | obvious mis-rerankings on validation set; precision matters more than latency | **settled** |
| D8 | Embedding model | `nomic-embed-text v1.5` via Ollama (768-dim, 8K ctx, Matryoshka-truncatable) | BGE-small-en-v1.5 (384-dim) for speed, or Qwen3-Embedding for quality | nomic latency too slow on enclave CPU, or MTEB shifts noticeably | **settled** |
| D9 | Fact temporality | Bi-temporal edges (Zep/Graphiti pattern) — never delete, set `t_invalid = new edge's t_valid` | Soft-tombstone with periodic compaction | bi-temporal filter cost grows past acceptable as edges hit ~10k+ | **settled** (convergence: Agent 5) |
| D10 | Write-time conflict resolution | Mem0's LLM-driven ADD / UPDATE / DELETE / NOOP decision against top-k similar existing facts | Pure append + dedup at query time | Mem0 batching of meeting-scale fact lists explodes LLM calls | **settled** (with caveat — see T2) |
| D11 | Entity resolution (people) | Roster-first via `resolve_identity` seam (you already have this), embedding+LLM fallback for unknown | Dedicated entity-resolution model | roster lookup misses >15% of named speakers | **settled** |
| D12 | Entity resolution (projects, topics) | Embedding similarity + LLM tiebreak on canonical_name | Open question — see O3 | dedup quality drops below acceptable | **open** |
| D13 | Extraction types | Five distinct: ActionItem, Decision, Commitment, OpenQuestion, Blocker — shared envelope (`source_quote, turn_ids[], person_id FKs, valid_from/valid_to`) | Collapse to one `Obligation` table with `type` enum | human annotators disagree >20% on type labels on validation set | **open** — see T2 |
| D14 | Extraction prompt shape | Schema-guided single-prompt-per-chunk producing all types at once | Per-type prompts (5× cost, sharper) | F1 on validation set fails by >15% vs. per-type | **open** — see T1 |
| D15 | Cross-encoder reranker | Defer | Add BGE-reranker after BM25+dense RRF | top-10 quality on validation set insufficient | **open** — see T3 |
| D16 | Importance scoring for facts | Use proxies (decision present? deadline present? named owner?) — no extra LLM pass | LLM-rated importance score (Generative Agents style) | retrieval ranking suffers without importance signal | **open** — see T4 |
| D17 | GraphRAG community detection (Leiden) | **Skip** at our scale — cohort itself IS the community | n/a (would require >>100x corpus growth) | corpus grows past ~10k transcripts | **settled** |
| D18 | Vector dimension storage | Matryoshka 256-dim primary; recompute 768-dim on demand | Pin 768-dim if Matryoshka quality drops | retrieval precision drops noticeably with 256 | **settled** |

---

## 2. Open tensions — decisions that need empirical input

Pulled out of the matrix above. These are the calls we can't make from the
literature alone — they require a small experiment on our 13-transcript fixture.

### T1 — Single-prompt vs. per-type extraction (D14)
**The question:** does one schema-guided prompt producing
`{action_items[], decisions[], commitments[], open_questions[], blockers[], entities[]}`
in one LLM call match the precision of five separate per-type prompts?
**Why it matters:** 5× LLM cost per chunk if per-type wins.
**Evidence so far:** Itext2KG uses two-pass (entities then relations); meeting-NLP
papers split per-type but at classifier-not-LLM cost; nothing directly tests
single-vs-multi prompt for modern instruction-tuned LLMs on this task.
**How to resolve:** measure on hand-coded ground truth (see §3 step 1).

### T2 — Action vs Commitment vs Decision separability (D13)
**The question:** are these three actually distinct in practice, or does one
combined `Obligation` table with a `type` enum suffice?
**Why it matters:** five tables vs one changes the SQL surface materially; if
humans can't agree on labels we'll be training the LLM to be confidently wrong.
**Evidence so far:** Purver 2007 and Lampert 2008 argue they're distinct
illocutionary acts; Granola/Fireflies/Otter collapse them in product UIs.
**How to resolve:** two-annotator agreement on 50 hand-coded examples. >80%
agreement → keep distinct. <80% → collapse to `Obligation{type}`.

### T3 — Cross-encoder reranker at small-corpus scale (D15)
**The question:** does BGE-reranker improve top-10 precision when we only have
~hundreds of docs and BM25+dense RRF top-10 may already be saturated?
**Why it matters:** another model in the enclave, +50-200ms per query.
**Evidence so far:** Anthropic's +67% retrieval-error reduction and the 15-25%
precision lift cited in production write-ups are all on enterprise-scale corpora
(100k+ docs). BEIR's smallest split is still 10-20× our size.
**How to resolve:** build a 20-50 query/transcript labeled eval set, measure
RRF top-10 NDCG; only add reranker if there's headroom.

### T4 — Importance scoring (D16)
**The question:** is an LLM-rated importance score (1-10, per extracted fact)
worth the extra inference pass, or do proxies (deadline present, named owner,
decision type) work as well for ranking?
**Why it matters:** importance enables Generative-Agents-style
recency×importance×relevance retrieval, but at +1 LLM call per fact.
**How to resolve:** evaluate retrieval ranking on the labeled eval set (T3) with
and without importance signal.

---

## 3. Proposed next-step experiments (LLM-light, decision-de-risking)

Three things to land on the 13-transcript fixture before any irreversible
architecture commits. All three are cheap (mostly hand-coding + Ollama; no
NearAI credits required).

### Step 1 — Hand-coded ground truth on 3 transcripts
Pick 3 of the 13 transcripts covering different shapes (one project intro, one
workshop, one 1-on-1 / discussion). Manually extract:
- ActionItems (with owner attempt + source quote)
- Decisions
- Commitments
- OpenQuestions
- Blockers
- Entities (Person, Project, Topic)

Do this with two annotators if at all possible — gives us T2's separability
number (cross-annotator agreement per type).

**Output:** `tests/fixtures/transcripts/<slug>.expected.yaml` for those 3 — also
serves as the C9 eval golden set deliverable.

### Step 2 — Single-prompt vs per-type bake-off
Two prompt variants against the 3 transcripts using Ollama (qwen2.5:14b):
- **A:** one schema-guided prompt producing all types at once
- **B:** five per-type prompts (action items / decisions / commitments /
  questions / blockers), entities extracted once

Measure F1 per type vs. hand-coded ground truth. Resolves T1.

### Step 3 — SQL schema sketch + 5 example queries (paper, no code)
Sketch the proposed schema:
- `entities (id, type, canonical_name, props_json)`
- `entity_mentions (entity_id, transcript_id, turn_id, raw_text, span)`
- `facts (id, type, subject_entity_id, object_entity_id, predicate, source_quote, evidence_chunk_id, valid_from, valid_to, confidence, ingested_at)`
- `chunks (id, transcript_id, turn_ids, text, context_header, embedding)`
- Extraction tables: either 5 typed (`action_items`, `decisions`, …) or 1 with `type`
- FTS5 virtual table on chunk + facts text
- sqlite-vec virtual table on chunk + fact embeddings

Then write SQL for 5 representative queries:
1. "What has Alex worked on across all transcripts?"
2. "Before my 1-on-1 with Sam, what's still open?"
3. "Show me decisions the cohort made about RAG."
4. "Find meetings related to this one." (semantic similarity)
5. "Who committed to what, by date?" (cross-transcript timeline)

If a query needs gymnastics, the schema is wrong — better to find that on paper.

---

## 4. Survey — Chunking strategies for LLM extraction from dialogue transcripts

> Source: Agent 1 (general-purpose, web search across LangChain, Jina, Anthropic,
> arXiv, AWS, Gladia, AMI, MeetingBank literature).
> Target: extraction-focused chunking (not pure retrieval), parameterized by
> model context window, dialogue-aware.

### 4.1 Candidate approaches

| # | Name | One-line description | When it wins | When it loses | Fit (1-5) | Source |
|---|------|----------------------|--------------|---------------|-----------|--------|
| 1 | Fixed-size / RecursiveCharacterTextSplitter | Greedy split on separators (`\n\n`, `\n`, `.`, ` `) with size+overlap | Simple, deterministic, cheap; fine on prose | Shreds dialogue across speaker turns; mid-sentence splits hurt extraction recall | 2 | [LangChain docs](https://docs.langchain.com/oss/python/integrations/splitters), [intuition issue #2026](https://github.com/langchain-ai/langchain/issues/2026) |
| 2 | Turn-aware / speaker-boundary chunking | Pack consecutive turns up to a budget, never split mid-turn, 10–20% overlap | Dialogue-native; preserves speaker attribution needed for "who committed to what" | A single long monologue can exceed the budget; needs a fallback splitter | **5** | [Gladia pipeline](https://www.gladia.io/blog/transcript-to-actionable-notes-llm), [AWS Nova meeting blog](https://aws.amazon.com/blogs/machine-learning/meeting-summarization-and-action-item-extraction-with-amazon-nova/) |
| 3 | Semantic chunking (Kamradt-style boundary) | Cosine-distance jumps between sentence/turn embeddings define cut points | Topic-coherent chunks → better single-topic extraction | Boundary thresholding is dataset-sensitive; "weak boundary" failure mode is documented | 4 | [Kamradt 5 Levels notes](https://medium.com/@anuragmishra_27746/five-levels-of-chunking-strategies-in-rag-notes-from-gregs-video-7b735895694d), [growing-window paper](https://www.sciencedirect.com/science/article/pii/S0950705125019343) |
| 4 | Proposition-based (Dense X) | LLM rewrites passages into atomic, self-contained factoids | Best for entity/decision atomicity; great retrieval density | Costly pre-pass; loses turn/speaker structure unless you carry metadata; needs a Propositionizer | 3 | [arXiv 2312.06648](https://arxiv.org/abs/2312.06648), [factoid-wiki](https://chentong0.github.io/factoid-wiki/) |
| 5 | Late chunking (Jina) | Embed whole doc with long-context model, then pool token spans into chunk embeddings | Each chunk embedding carries doc-wide context — fixes "pronoun/referent" loss in transcripts | An embedding-time trick; doesn't help LLM extraction prompts directly (only retrieval) | 3 | [Jina blog](https://jina.ai/news/late-chunking-in-long-context-embedding-models/), [arXiv 2409.04701](https://arxiv.org/abs/2409.04701) |
| 6 | Hierarchical / RAPTOR | Cluster + recursively summarize chunks into a tree; query at any level | Great cross-meeting synthesis ("what does X care about across 5 sessions?") | Build cost grows with corpus; reduce-step degradation compounds across levels | 4 | [arXiv 2401.18059](https://arxiv.org/abs/2401.18059) |
| 7 | Contextual Retrieval (Anthropic) | Prepend a 1–2 sentence LLM-generated context blurb to each chunk before embed/extract | -67% retrieval error reported; recovers anaphora/speaker context cheaply | One extra LLM call per chunk; needs prompt caching to be affordable | 4 | [Anthropic cookbook](https://platform.claude.com/cookbook/capabilities-contextual-embeddings-guide) |
| 8 | Agentic chunking | LLM decides boundaries (and chunk type) dynamically per document | Adapts to mixed formats (1:1 vs panel vs intro) | Non-deterministic, expensive, hard to debug at 100s of docs | 2 | [Kamradt L5](https://medium.com/@anuragmishra_27746/five-levels-of-chunking-strategies-in-rag-notes-from-gregs-video-7b735895694d) |
| 9 | Action-Item-Driven Segmentation | Topic-segment first (spectral / dynamic), then run extraction per section, then merge | Purpose-built for meeting action items; matches your first-class extractables | Adds a topic-seg dependency; quality depends on segmentation model | 4 | [arXiv 2312.17581](https://arxiv.org/abs/2312.17581), [MIDC arXiv 2303.16763](https://arxiv.org/pdf/2303.16763) |

### 4.2 Primary
**Turn-aware chunking + per-chunk context header (hybrid of #2 + #7), parameterized by model context.**
Pack consecutive speaker turns up to `target = min(model_ctx × 0.4, 6k tokens)`
with `overlap = 1–2 turns`, never split mid-turn except via a fallback recursive
splitter when a single turn exceeds budget. Prepend a 1–2 sentence
Claude/Qwen-generated context header per chunk ("This is meeting M with A, B;
chunk covers minutes 12–18; prior context: project X kickoff"). Preserves the
speaker attribution your action-item/commitment extraction depends on, survives
model swap (chunk size is a function of `model_ctx`, not a constant), runs
entirely in-enclave. Aligns with `d981345 transcripts: turn-aware chunking with
overlap + pipeline constants`.

### 4.3 Fallbacks
- **RAPTOR-style hierarchical summary tree** (#6) — for the *cross-transcript*
  layer once we have >~50 transcripts and "before your meeting with X" needs
  cohort-level synthesis rather than per-meeting recall. Trigger: per-meeting
  extraction is good but cross-meeting answers feel shallow.
- **Proposition-based extraction** (#4) — for per-chunk content when entity/decision
  precision matters more than speaker context (e.g. building a "commitments
  ledger"). Trigger: dedup/merge of action items across meetings becomes the
  dominant pain.

### 4.4 Open questions
- **Principled context→chunk mapping.** Literature gives rules of thumb
  (`chunk_size ≈ 1k–4k`, overlap 10–20%). No paper convincingly establishes
  `chunk = 0.4 × ctx` as optimal for *extraction* (vs retrieval). Needs an
  empirical sweep on our 13 transcripts with Qwen-14B (8k) and a 200k cloud model.
- **Reduce-step degradation curve.** Map-reduce literature flags reduce-step loss
  ([Galileo](https://galileo.ai/blog/llm-summarization-strategies),
  [Google Cloud](https://cloud.google.com/blog/products/ai-machine-learning/long-document-summarization-with-workflows-and-gemini-models))
  but doesn't quantify how many partials before action-item recall collapses.
- **The "20-min monologue" edge case.** No published meeting-specific recipe.
  Candidates: (a) recursive sentence-split inside the turn with overlap;
  (b) topic-segment the turn with semantic chunking (#3); (c) summarize-then-
  extract. Untested at our scale.
- **Context-header cost vs benefit at small scale.** Anthropic's 67% retrieval-
  error reduction is on large corpora. Whether it pays back the per-chunk LLM
  call when we have hundreds (not millions) of chunks, on a smaller local model,
  is unknown.

---

## 5. Survey — Knowledge graph construction + GraphRAG family

> Source: Agent 2 (general-purpose, GraphRAG and KG-from-text literature).
> Target: extract typed entities and relations from transcripts into a queryable
> graph; storage-agnostic; small corpus (hundreds of docs, ~50 people).

### 5.1 Candidate approaches

| Name | One-line description | When it wins | When it loses | Fit (1-5) | Link |
|---|---|---|---|---|---|
| **Microsoft GraphRAG** | LLM entity/relation extraction → Leiden community detection → hierarchical community summaries → local+global query | Massive corpora with unknown structure, "global sensemaking" questions | Small corpora where communities are tiny/degenerate; expensive (multi-pass LLM per chunk + per community) | 2 | [microsoft/graphrag](https://github.com/microsoft/graphrag), [paper](https://arxiv.org/abs/2404.16130) |
| **nano-graphrag** | ~1100 LOC minimalist GraphRAG clone, swappable storage/LLM, NetworkX default | You want GraphRAG semantics but readable/hackable code; good reference impl | Production-grade ops, large scale | 4 (as reference) | [gusye1234/nano-graphrag](https://github.com/gusye1234/nano-graphrag) |
| **LightRAG** | Dual-level retrieval (low=entities, high=themes), incremental insert, simpler than GraphRAG | Continuously-growing corpora, lower extraction cost, no community detection step | Pure global summarization queries | 4 | [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG), [paper](https://arxiv.org/abs/2410.05779) |
| **HippoRAG / HippoRAG 2** | Build open-KG once, Personalized PageRank from query entities for multi-hop retrieval | Multi-hop factual queries on stable KG; cheap per-query (no LLM at retrieval) | Heavy incremental churn; needs decent entity linking | 4 | [OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG), [paper](https://arxiv.org/abs/2405.14831) |
| **LangChain LLMGraphTransformer + Neo4j** | Prompt-LLM-to-emit-(node,rel,node) with `allowed_nodes`/`allowed_relationships` schema constraints; persist to Neo4j/Memgraph | You have a real graph DB and a clean schema; mature Cypher tooling | Heavyweight dep for ~hundreds of docs in an enclave | 3 | [docs](https://python.langchain.com/docs/how_to/graph_constructing/), [Neo4j blog](https://neo4j.com/developer-blog/construct-knowledge-graphs-unstructured-text/) |
| **REBEL (closed-set RE)** | Seq2seq model emitting (head, rel, tail) over a fixed relation inventory; no LLM at extraction time | High-precision relation extraction at low cost, deterministic | Closed Wikidata-style relations don't match our domain (Commitment, OpenQuestion); needs separate NER | 2 | [Babelscape/rebel](https://github.com/Babelscape/rebel-large), [paper](https://aclanthology.org/2021.findings-emnlp.204/) |
| **Triplex / KG-Gen** | Small fine-tuned models (Triplex 3B) that emit schema-constrained triples cheaply | Throughput-bound pipelines; on-device extraction | Schema drift; less flexible than prompt-based LLM | 3 | [SciPhi-AI/Triplex](https://huggingface.co/SciPhi/Triplex), [KG-Gen](https://arxiv.org/abs/2502.09956) |
| **Itext2KG / "schema-first" prompt extraction** | Two-pass: extract entities, then relations, constrained by JSON-schema/Pydantic | Known ontology like ours; resolves entities incrementally; storage-agnostic | Loses serendipitous edges open extraction would catch | **5** | [AuvaLab/itext2kg](https://github.com/AuvaLab/itext2kg), [paper](https://arxiv.org/abs/2409.03284) |

### 5.2 Primary
**Schema-guided extraction (Itext2KG-style) + LightRAG-style dual retrieval, persisted as a property graph in SQLite.**
Our ontology is fixed and small (8 node types: Person, Project, Topic, Decision,
ActionItem, Commitment, OpenQuestion, Meeting), so prompting the LLM with a
Pydantic/JSON-schema (`extract_entities(schema) -> extract_relations(allowed_types)`)
gives precision wins without paying for Leiden community detection (degenerate at
~hundreds of docs and ~50 people). LightRAG's incremental insert pattern
(entity-merge on canonical key, no full re-extraction) maps cleanly onto our
"transcripts added continuously" constraint, and onto SQLite tables:
- `nodes(id, type, canonical_name, props_json)`
- `edges(src, dst, type, evidence_meeting_id, confidence)`
- `mentions(node_id, meeting_id, span)`

Practitioners at 10²–10⁴ docs overwhelmingly pick SQL-with-edge-tables or
DuckDB+NetworkX over standing up Neo4j in an enclave (see nano-graphrag's default
`NetworkXStorage` and LightRAG `KVStorage` backend). For "meeting prep with X":
1-2 hop walk from the Person node (cheap in SQL with recursive CTE), rank by
`(recency, edge_confidence, co-occurrence_count)`. HippoRAG's Personalized
PageRank is a drop-in upgrade once we have >1 hop ambiguity.

### 5.3 Fallbacks
- **nano-graphrag with community detection disabled** — if open extraction
  surfaces materially better edges in eval. Gives the GraphRAG local-search query
  pattern (entity-centric retrieval) for free. Trigger: schema-constrained
  extraction misses >20% of human-judged useful edges on a labeled subset.
- **HippoRAG 2 on top of the existing graph** — when single-hop walks stop
  answering "what decisions did Alex make about projects related to RAG?" well.
  PPR handles 2-3 hop ranking without re-prompting an LLM per query. Trigger:
  multi-hop eval recall < 0.6.

### 5.4 Open questions
- **Entity resolution at small scale.** SOTA is unsettled — LightRAG/GraphRAG do
  LLM-based name-merge per insert, HippoRAG uses dense-embedding synonyms,
  Itext2KG uses cosine over entity-embedding + LLM tiebreak. For 10-50 known
  people, our seeded roster (already in `resolve_identity`) likely beats all of
  these; the open question is Project/Topic dedup where there's no roster
  ([survey](https://arxiv.org/abs/2402.06801)).
- **Schema-guided vs open extraction quality.** Published comparisons (Itext2KG,
  KG-Gen, GLiNER-based pipelines) show schema-guided wins on precision but loses
  10-30% recall of "interesting" edges. Worth a small ablation on our 13
  transcripts.
- **Community summarization at our scale.** GraphRAG docs note communities need
  ~thousands of entities to be meaningful; with ~50 people and a few dozen
  projects, Leiden produces 2-5 trivial communities. Skip unless corpus grows 100×.
- **Incremental update correctness.** None of these systems cleanly handle
  *retraction* (a later meeting overrides an earlier decision). We need an
  explicit `superseded_by` edge type and timestamped edges — not covered by any
  off-the-shelf GraphRAG variant.

---

## 6. Survey — Hybrid retrieval & multi-store composition

> Source: Agent 3 (general-purpose, hybrid retrieval + embedded vector store +
> embedding model research).
> Target: pick retrieval pattern, embedded vector store, and local embedding
> model that compose with SQLite inside a Phala CVM at small-corpus scale.

### 6.1 Candidate approaches

| Name | One-line description | When it wins | When it loses | Fit (1-5) | Citation |
|---|---|---|---|---|---|
| **BM25 only (SQLite FTS5)** | Lexical ranking over chunks via SQLite's built-in FTS5 BM25 | Names, jargon, exact phrases ("RAG", "Phala", person names) | Paraphrases, synonyms ("decisions about retrieval" vs "RAG choices") | 4 | [Alex Garcia, sqlite-vec hybrid](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html) |
| **Dense (bi-encoder) only** | Cosine over sentence-transformer embeddings in sqlite-vec/lancedb | Paraphrase, "find related meetings" semantic intent | Loses on proper nouns, acronyms, code/IDs; needs warm embedding model | 3 | [Ranjan Kumar, BM25 vs Dense](https://ranjankumar.in/bm25-vs-dense-retrieval-for-rag-engineers) |
| **BM25 + Dense via RRF** | Run both, fuse with `1/(60+rank)` — score-scale agnostic | Mixed query workload (ours), reliably +15-30% recall over either alone | Adds an embedding pass; latency ~2× dense alone | **5** | [Brenndoerfer hybrid](https://mbrenndoerfer.com/writing/hybrid-search-bm25-dense-retrieval-fusion), [ceaksan SQLite RRF](https://ceaksan.com/en/hybrid-search-fts5-vector-rrf) |
| **ColBERT / late-interaction rerank** | MaxSim over per-token vectors, used as a reranker on top-50 | Hard paraphrase + entity queries where bi-encoder ranks are noisy | Per-token index is ~10-50× larger; overkill at hundreds of docs | 2 | [Sease, ColBERT in Practice](https://sease.io/2025/11/colbert-in-practice-bridging-research-and-industry.html) |
| **Cross-encoder rerank (BGE-reranker)** | Rerank top-K from RRF with a small cross-encoder | Cheap, high-precision lift on top of RRF; runs CPU-only | Adds 50-200ms per query; needs another model in the enclave | 4 | [TianPan hybrid prod](https://tianpan.co/blog/2026-04-12-hybrid-search-production-bm25-dense-embeddings) |
| **GraphRAG (graph-walk + vector backfill)** | Entity graph → expand subgraph → pull chunks → LLM rerank | Multi-hop ("what did Alex and Sam discuss across meetings?"); 1-on-1 prep | Heavy: needs entity extraction quality we don't yet have; complex eval | 3 | [Neo4j adv RAG](https://neo4j.com/blog/genai/advanced-rag-techniques/), [Milvus VectorGraph](https://milvus.io/blog/vector-graph-rag-without-graph-database.md) |
| **Agentic / query routing** | LLM tool-calls SQL vs vector vs graph per query | "What has Alex worked on?" routes to SQL; "related meetings" routes to vector | At hundreds of docs, fan-out + rerank is cheaper than a routing LLM call | 3 | [futureagi Agentic RAG](https://futureagi.com/blog/agentic-rag-systems-2025/) |
| **sqlite-vec + FTS5 (one file)** | Vectors and BM25 in the same SQLite DB; one transaction | Our stack is already SQLite-first; redeploy = copy one file; enclave-trivial | Less mature ANN than lancedb for >1M vectors (not our problem) | **5** | [AIngram local-first memory](https://github.com/bozbuilds/AIngram), [liamca/sqlite-hybrid-search](https://github.com/liamca/sqlite-hybrid-search) |
| **LanceDB embedded** | Columnar on-disk vector store, IVF-PQ, larger-than-RAM | Millions of vectors, columnar analytics on metadata | Separate file format from SQLite; we'd run two stores | 3 | [4xxi LanceDB vs](https://4xxi.com/articles/vector-database-comparison/) |
| **ChromaDB embedded** | Python-first vector DB, Rust core in 2025 | Fastest prototype-to-working; great if you want vectors-as-a-service feel | Yet another data dir to persist across enclave redeploys | 2 | [Encore Best Vector DBs 2026](https://encore.dev/articles/best-vector-databases) |
| **BGE-small-en-v1.5 (384-dim)** | 33M params, MTEB ~62, fast CPU | CPU-only enclave, hundreds of docs, English | Slightly weaker on long context | 4 | [BentoML guide](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models) |
| **nomic-embed-text v1.5 (768-dim, 8K ctx)** | 137M params, MTEB 62.4, 8K context, Ollama-native | We already run Ollama; 8K context fits a transcript chunk; Matryoshka lets us truncate to 256-dim | Slightly bigger model in the enclave | **5** | [Morph Ollama embeddings](https://www.morphllm.com/ollama-embedding-models) |
| **GTE-large-en-v1.5 / BGE-large** | 335M params, MTEB ~65 | Top quality and have GPU/RAM headroom | Overkill on CPU at this scale | 3 | [Baseten OSS embeddings](https://www.baseten.co/blog/the-best-open-source-embedding-models/) |

### 6.2 Primary
- **Retrieval pattern:** BM25 (FTS5) + dense cosine, fused with **Reciprocal Rank Fusion (k=60)**, top-50 → optional BGE-reranker-base cross-encoder for top-10 (deferred — see T3).
- **Vector store:** **sqlite-vec** in the same `.sqlite` file as relational data.
- **Embedding model:** **nomic-embed-text v1.5** via Ollama.

**Why this fits:**
- One file persists across Phala redeploys — same operational story as existing
  SQLite. No second data dir, no extra service, no network hop.
- RRF is score-scale agnostic — no weight tuning between BM25 and cosine.
- Mixed proper-noun + paraphrase query workload → +15-30% over either alone
  per BEIR + production write-ups.
- nomic-embed-text runs natively in the Ollama instance already in use for
  qwen2.5 — no second model server in the CVM, 8K context covers a turn-aware
  chunk, Matryoshka means storing 256-dim and recomputing 768-dim cheaply.

### 6.3 Fallbacks
1. **GraphRAG-style entity walk** on top of RRF when "1-on-1 prep" and multi-hop
   queries become dominant. Trigger: cohort grows past ~100 people OR multi-
   person/multi-meeting recall plateaus. SQLite tables (`entities` + `entity_
   mentions` + `co_occurrences`) — no separate graph DB needed.
2. **LLM query router** (qwen2.5 tool-calls `sql_search` / `vector_search` /
   `graph_walk`) when obvious mis-routes appear — e.g. "what did Alex work on"
   returning semantic neighbors instead of an entity filter. Until then,
   fan-out + RRF is cheaper and more predictable.

### 6.4 Open questions
- **Cross-encoder reranker worth it at N=hundreds?** +15-25% precision lift is
  measured on enterprise corpora; at 13-300 transcripts the top-10 may already
  be saturated. Measure before adding.
- **Chunk granularity for RRF.** BM25 prefers shorter chunks (term density);
  dense often prefers longer (semantic context). Turn-aware chunking may need
  two different chunk sizes per modality.
- **Embedding model swap cost.** nomic v1.5 is good now; Qwen3-Embedding /
  GTE-Qwen2 climbing MTEB fast. Design `embeddings(model_id, dim, vec)` so we
  can A/B without re-ingest.
- **Principled small-corpus retrieval literature.** Mostly no — BEIR's smallest
  split (SciFact, ~5K) is still 10-20× our size. Need a tiny internal eval set
  (20-50 hand-labeled query/transcript pairs) because no public benchmark
  matches the regime.

---

## 7. Survey — Meeting NLP + action / decision / commitment extraction

> Source: Agent 4 (general-purpose, academic meeting-NLP and industry-shipped
> action-item schema research).
> Target: extraction schema for action items, decisions, commitments, open
> questions, blockers from diarized meeting transcripts.

### 7.1 Candidate approaches

| Name | One-line description | When it wins | When it loses | Fit (1-5) | Citation |
|---|---|---|---|---|---|
| **AMI/ICSI dialogue-act + decision/action subdialogue tagging** | Classifier pipeline: DA tags (SWBD-DAMSL inspired) → identify decision/action subdialogues → extract spans | Long, well-structured meetings with clear turn-taking; gives reusable DA labels | Short intros; brittle outside training domain; expensive to retrain | 2 | [AMI Corpus](https://groups.inf.ed.ac.uk/ami/corpus/); [Bui et al. 2009](https://aclanthology.org/W09-3934/) |
| **MeetingBank summarization schema** | Section-level abstractive summaries with extractive grounding (source-span pointers) | Auditable, citable summaries tied to transcript spans | Doesn't natively model action/decision/commitment as distinct types | 3 | [Hu et al. ACL 2023](https://aclanthology.org/2023.acl-long.906/) |
| **QMSum query-focused extraction** | Train/prompt model to answer arbitrary queries against meeting, e.g. "what did X commit to?" | Powers our "meeting prep for X" use case directly; flexible schema-free | Slow at scale; non-deterministic outputs hard to dedupe across meetings | 4 | [Zhong et al. NAACL 2021](https://aclanthology.org/2021.naacl-main.472/) |
| **Cohan et al. / "Action-Item Detection in Meeting Transcripts" LLM era** | Few-shot LLM with structured JSON: owner, action, deadline, source_turn | Modern default; works with 14B models; easy to evolve schema | Hallucinated owners on hedged speech; misses implicit assignments | **5** | [Cohan et al. EMNLP 2023](https://aclanthology.org/2023.emnlp-industry.71/); [Pereira et al. 2024](https://arxiv.org/abs/2409.06044) |
| **Granola / Fireflies / Fellow / tl;dv schema (industry convergence)** | `{title, assignee, due_date, source_quote, timestamp, status}` + separate Decisions + Questions | Battle-tested UX; assignee + source_quote enable cross-meeting joining | Owner resolution mostly text-match to participant list; no commitment vs decision distinction | **5** | [Fireflies action items](https://fireflies.ai/blog/action-items); [Fellow API](https://fellow.app/api/); [Granola templates](https://www.granola.ai/templates) |
| **Microsoft Copilot Teams Intelligent Recap schema** | `recap.actionItems[]{title, assignee, sourceUtteranceId}`, `recap.decisions[]`, `recap.followUps[]` with utterance-anchor IDs | Strong utterance-level anchoring = perfect for cross-meeting joins on a person | Closed schema; can't see model internals | 4 | [Teams Intelligent Recap](https://learn.microsoft.com/en-us/microsoftteams/intelligent-recap); [Graph aiInsight](https://learn.microsoft.com/en-us/graph/api/resources/aiinsight) |
| **Google Meet "Take Notes for Me" schema** | Summary + Action items `{description, assignee}`; no decisions/questions broken out | Minimal, robust default | Loses decisions, blockers, open questions — wrong for our product goal | 2 | [Google Meet AI notes](https://support.google.com/meet/answer/14754931) |
| **Commitment Detection (CMU/IBM line)** | Treat commitments as distinct illocutionary class — "I will X" vs "we should X" vs "decided X" | Tracking promises by person across meetings | Small literature; classifiers brittle | 4 | [Purver et al. 2007](https://aclanthology.org/W07-1623/); [Lampert et al. 2008](https://aclanthology.org/I08-2113/) |
| **Open-question / unresolved-issue extraction** | Detect interrogatives + unanswered-status via discourse tracking | High product value (gap territory) | Effectively unsolved at scale — mostly heuristic in industry | 4 | [Asher & Lascarides SDRT](https://www.cambridge.org/core/books/logics-of-conversation/); [Wang et al. 2023](https://arxiv.org/abs/2305.04982) |

**Convergence note**: Granola, Fireflies, Fellow, tl;dv, Fathom, Read all ship
the same core triple — **Action Items, Decisions, Key Topics** — but only Fellow
and Copilot expose stable per-item IDs you can join on across meetings. None
ship dialogue acts as a user-facing primitive; DA tagging is dead in product,
alive only as an internal feature.

### 7.2 Primary schema

Five extraction types, all sharing a common envelope to enable cross-meeting
joins:

**Common envelope (every extraction)**:
```
id (uuid), transcript_id, turn_ids[], source_quote,
extracted_at, confidence (0-1), model_version,
status_inferred ("open" | "resolved" | "unclear")
```

**ActionItem**:
```
description, owner_person_id (nullable), owner_raw_text,
assignee_evidence ("self-assigned" | "named" | "implied" | "unassigned"),
due_date_iso (nullable), due_date_raw, depends_on[]
```

**Decision**:
```
decision_text, alternatives_considered[],
decided_by_person_ids[], reverses_decision_id (nullable)
```
Distinct from action items because decisions have no owner-to-execute; they
constrain future action.

**Commitment**:
```
commitment_text, committer_person_id,
beneficiary_person_id (nullable),
commitment_type ("will_do" | "will_share" | "will_decide" | "will_followup")
```
Distinct from action items because the speaker is binding themselves, with no
third-party assignment needed.

**OpenQuestion**:
```
question_text, raised_by_person_id, addressed_to_person_id (nullable),
answered (bool), answer_turn_id (nullable), topic_tags[]
```

**Blocker**:
```
blocker_text, blocks_what (action_item_id | decision_id | freeform),
owned_by_person_id (nullable), external (bool)
```

**Why**: the shared envelope (`source_quote` + `turn_ids` + `person_id` foreign
keys) is what makes data **connectable** — the meeting-prep query becomes a SQL
join on `person_id` across all five tables. Splitting action/decision/commitment
matches the empirical evidence in Purver 2007 and Lampert 2008 that these are
distinct illocutionary acts with different downstream uses
(execute / constrain / track-as-promise). OpenQuestion + Blocker are gap
territory in industry — owning these is differentiation.

### 7.3 Fallbacks
- **Fallback A** — Collapse Action/Commitment/Decision into one `Obligation`
  table with a `type` enum. Trigger: LLM extraction shows <60% agreement
  between human-coded action vs commitment on a 50-item validation set →
  the distinction isn't reliably extractable at 14B, collapse.
- **Fallback B** — QMSum-style query-time extraction instead of pre-extraction.
  Trigger: pre-extraction recall on action items stays below ~70% → do lazy
  extraction at meeting-prep time, scoped to the target person.

### 7.4 Open questions
- **Owner resolution accuracy on real transcripts.** How often does qwen2.5:14b
  correctly resolve "I'll do it" / "can you handle that?" / "we should…" to a
  person_id given a participant roster? Pereira et al. 2024 reports 75-85% on
  clean cases, much worse on implied/group assignments — needs measurement on
  our 13 transcripts before scaling.
- **Action vs Commitment vs Decision separability.** Do two human annotators
  agree on the type label >80% of the time? If not, Fallback A.
- **Hedging false-positive rate.** "maybe we could…" / "I might…" — what
  fraction get extracted as actions/commitments? Industry tools over-extract
  here; tune prompt for hedging-aware filtering and measure.
- **Short-meeting (10-15 turn intros) extraction yield.** Does meaningful
  extraction happen, or should intros skip extraction and only produce a
  participant/topic record? Likely diverges sharply from 90-min workshops.

---

## 8. Survey — Agent memory systems

> Source: Agent 5 (general-purpose, Mem0/MemGPT/Letta/Zep/A-MEM literature).
> Target: production agent-memory designs for extraction unit, storage shape,
> update/conflict logic, cross-episode linking.

### 8.1 Candidate approaches

| System | Unit of memory | Storage | Update logic | Fit (1-5) | Link |
|---|---|---|---|---|---|
| **Mem0** | Free-form NL "fact" statements (LLM-extracted from message-pair + summary + 10-msg window) | Vector DB (Qdrant/Chroma/etc.); graph variant uses entity/relation triples | LLM tool-call returns ADD / UPDATE / DELETE / NOOP against top-10 similar memories; DELETE marks invalid (kept for temporal reasoning) | **5** | [arXiv 2504.19413](https://arxiv.org/html/2504.19413v1), [State of Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026) |
| **Zep / Graphiti** | Three subgraphs: Episode (raw), Entity (deduped), Community (clusters); facts = labeled edges, can be hyper-edges | Neo4j-style temporal KG; bi-temporal (T = event time, T′ = ingest time) with `t_valid` / `t_invalid` per edge | New edge contradicting overlapping edge sets old edge's `t_invalid = new edge's t_valid` — old facts never deleted, just expired | **5** | [arXiv 2501.13956](https://arxiv.org/html/2501.13956v1), [Graphiti blog](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/) |
| **A-MEM** | Atomic "note" with 7 fields: content, timestamp, LLM-keywords, LLM-tags, LLM contextual description, embedding, link set | ChromaDB | New note → top-k cosine retrieve → LLM judges which existing notes to link AND which to *rewrite* (keywords/tags/description) — "memory evolution" | 4 | [arXiv 2502.12110](https://arxiv.org/html/2502.12110v11), [agiresearch/a-mem](https://github.com/agiresearch/a-mem) |
| **MemGPT / Letta** | Free-form blocks in 3 tiers: core (in-context, model edits), recall (full message log), archival (vector) | Postgres + pgvector by default; tier movement is LLM tool calls | Model decides when to promote/demote via `core_memory_append`, `archival_memory_insert`; no built-in conflict resolution — agent reconciles in-context | 2 | [Letta docs](https://docs.letta.com/concepts/letta/), [walkthrough](https://sureprompts.com/blog/letta-memgpt-walkthrough) |
| **Generative Agents (Park 2023)** | Free-form "observations" in a memory stream; periodic LLM "reflections" written back as higher-level memories | Append-only stream | No overwrite. Retrieval = weighted sum of recency + importance (1-10 LLM score) + cosine relevance. Reflections summarize bursts of high-importance events | 3 | [arXiv 2304.03442](https://ar5iv.labs.arxiv.org/html/2304.03442) |
| **LangGraph + LangMem** | JSON docs in namespaced key/value Store; semantic = profile OR collection; episodic = few-shot examples; procedural = prompt | Any BaseStore (Postgres, in-memory) with optional embedding index | `MemoryManager` LLM decides insert / update / delete, versioned history; profile-style requires regenerating whole JSON (error-prone) | 3 | [LangGraph memory docs](https://docs.langchain.com/oss/python/langgraph/memory), [LangMem](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/) |
| **OpenAI ChatGPT Memory** | Short NL "saved memories" + (April 2025) reference-all-chats vector recall | Separate vector store, injected into system prompt | LLM extracts during chat; user can edit/forget; "Memory updated" notifications imply implicit upsert, no public spec on conflict logic | 2 | [Memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq) |
| **AutoGen Teachability** | (input, output) memo pairs | ChromaDB | Pure append; retrieval-only; no conflict resolution | 1 | [autogen_ext.memory.chromadb](https://microsoft.github.io/autogen/dev//reference/python/autogen_ext.memory.chromadb.html) |

**Benchmark context**: on LongMemEval (chat-derived), Zep ~63.8% vs Mem0 ~49%
with GPT-4o per the 2025 paper; Mem0's 2026 self-reported numbers (94.4) reflect
a redesigned algorithm with multi-signal retrieval
([LongMemEval](https://github.com/xiaowu0162/longmemeval),
[State of Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)).

### 8.2 Primary
**Zep/Graphiti's three-subgraph + bi-temporal model — steal the *shape*, not the Neo4j dependency.**

Meeting transcripts are inherently episodic (one meeting = one episode),
multi-participant (entity nodes are first-class — Alex, Priya, the cohort), and
the most valuable connections are exactly the temporally evolving facts ("Alex
pivoted from X to Y on date D") that Graphiti's bi-temporal edges encode
natively. Episode→Entity→Community hierarchy maps cleanly onto
transcript→person/project→cohort-theme. Never-delete-only-invalidate is
critical for meeting prep ("what did Alex commit to last time, still active?").
SQLite holds entity/edge tables with `valid_from`, `valid_to`, `ingested_at`
columns — no graph DB at 13–hundreds of transcripts. FK joins + vector index on
edge `fact` text covers retrieval.

**Layered on top: Mem0's ADD/UPDATE/DELETE decision call as the *write-side* policy** when a newly-extracted edge collides with an existing one between the
same entity pair. Mem0's prompt is the cleanest shipped recipe for conflict
resolution and is the system explicitly engineered for that decision.

### 8.3 Fallbacks
- **Mem0-only (NL facts + LLM upsert) on SQLite + embeddings.** Trigger: entity
  resolution turns out to be the bottleneck (ambiguous names, renamed projects)
  and graph maintenance cost exceeds retrieval benefit. Mem0 is much simpler to
  ship; keep the UPDATE logic, drop the graph. Identity-linkage is already a
  seam (`resolve_identity`) so Mem0-style flat memories per `person_id` slot in.
- **A-MEM (linked notes) on Chroma.** Trigger: product question shifts from
  "what's true now about Alex's project" to "show me thematically related
  moments across meetings." A-MEM's LLM-judged link generation and write-back
  rewriting of neighbor notes' tags/descriptions is the best shipped pattern
  for *cross-episode linking as a first-class operation* — closest to our
  "connection-finding" framing. Weaker on temporal correctness.

### 8.4 Open questions
- **Chat→meeting transplant of update logic.** Mem0/Zep both assume short turns
  where each new message is a small candidate fact. A 60-min meeting yields
  dozens of candidate facts at once; running ADD/UPDATE/DELETE against the store
  *per extracted fact* may explode LLM calls. Turn-aware chunking helps, but
  does Mem0's prompt still work when "new info" is itself a 10-fact batch?
  Needs experiment on 2-3 transcripts.
- **Who is the "user"?** All these systems assume one user-bot dyad and a
  personal memory. In a cohort, every transcript involves N people and the
  memory is *shared*. Mem0 has per-user namespaces; Zep's entity nodes don't
  care — but retrieval-time scoping ("show me Alex's commits, not the
  cohort's") is something none handle out of the box.
- **Importance scoring without a live agent.** Generative Agents'
  recency+importance+relevance works because an agent rates importance at
  write time. For offline batch ingest, we'd need an LLM importance pass per
  extracted fact — worth it, or use proxies (decision present? deadline
  present? named owner)?
- **Bi-temporal in SQLite.** Zep's invalidation is conceptually clean but
  operationally requires every retrieval to filter `t_invalid IS NULL OR
  t_invalid > query_time`. Confirm this stays cheap as edge count grows into
  the tens of thousands; if not, soft-tombstone with periodic compaction.

---

## 9. Cross-cutting synthesis — the unified picture

The five surveys, read together, sketch one coherent architecture:

**A bi-temporal entity-fact graph in SQLite, fed by schema-guided extraction
over turn-aware chunks, with hybrid retrieval at query time.**

### 9.1 Storage layout (proposed)

All in one `.sqlite` file:

```
-- existing
transcript_sessions     (raw, immutable — write-once invariant)

-- new (chunking & retrieval layer)
chunks                  (id, transcript_id, turn_ids[], text, context_header,
                         embedding_id, fts_doc_id)
chunks_fts              (FTS5 virtual table over chunks.text + context_header)
chunks_vec              (sqlite-vec virtual table; embedding by chunk_id)

-- new (entity-fact graph layer)
entities                (id, type, canonical_name, props_json, embedding_id)
entity_mentions         (entity_id, transcript_id, turn_id, raw_text, span)
facts                   (id, type, subject_entity_id, object_entity_id,
                         predicate, source_quote, evidence_chunk_id,
                         valid_from, valid_to, confidence, ingested_at,
                         superseded_by)

-- new (extraction tables — D13 open: 5 tables vs 1 with type enum)
action_items / decisions / commitments / open_questions / blockers
(all share envelope: id, transcript_id, turn_ids[], source_quote,
 confidence, model_version, status_inferred,
 + type-specific fields per §7.2)

-- model-agnostic embedding storage
embeddings              (id, model_id, dim, vec)  -- A/B swap without re-ingest
```

### 9.2 Pipeline (proposed)

```
parse transcript
  → turn-aware chunks (size = f(model_ctx))
  → per-chunk context header (Anthropic Contextual Retrieval)
  → embed each chunk (nomic-embed-text → embeddings + chunks_vec)
  → FTS5 index (chunks_fts)
  → per-chunk schema-guided LLM extraction
      → produces: entities, facts, action_items, decisions,
                  commitments, open_questions, blockers
  → entity resolution
      → people: roster lookup first (resolve_identity seam)
      → projects/topics: embedding similarity + LLM tiebreak
  → write-time conflict resolution (Mem0 ADD/UPDATE/DELETE/NOOP)
      → if updating: bi-temporal — set old fact's valid_to = new fact's valid_from
  → store
```

### 9.3 Retrieval patterns (proposed)

| Query type | Path |
|---|---|
| "What has Alex worked on?" | SQL filter on `entity_mentions` + `facts` by `person_id`, group by transcript, order by `valid_to DESC NULLS FIRST` |
| "Find related meetings to this one" | sqlite-vec cosine over chunk embeddings; group by transcript; rerank by participant overlap |
| "What decisions did the cohort make about RAG?" | FTS5 + dense RRF over chunks → expand to `facts.type='Decision'` linked to retrieved chunks |
| "Before my 1-on-1 with Sam, what's still open?" | SQL filter `open_questions` + `action_items` + `commitments` where `Sam IN persons AND status_inferred='open'` ORDER BY recency; optional rerank by topic similarity to a seed |
| "Who committed to what?" (timeline) | SQL on `commitments` joined to `entities`, order by `valid_from` |
| Multi-hop ("decisions Alex made about RAG-adjacent projects") | Recursive CTE over `facts` from Person → 2-hop expand; rerank by recency × confidence |

### 9.4 Model-agnostic discipline

What survives a backend swap (NearAI ↔ Ollama qwen2.5:14b ↔ future):
- Chunk size = `min(model_ctx × 0.4, 6k tokens)` — formula, not constant
- Reduce step bounded by partial count K → hierarchical when K exceeded
- `enrich_prompt_version` already tracks prompt changes (per IMPLEMENTATION_PLAN
  §D)
- `embeddings(model_id, dim, vec)` table → A/B embedding models without
  re-ingest
- `facts.model_version` → which model produced each fact (provenance for
  re-enrichment passes)

### 9.5 What changes vs. current `BUILD_PLAN.md` / `IMPLEMENTATION_PLAN.md`

The build plan and implementation plan describe Phase 1 (parse → 1-pass enrich
→ store → dashboard). This survey doesn't contradict that — but it sharpens
what Phase 2 looks like:

- Phase 1's `derived.summary / signals / entities` schema (per `models.py`) is a
  reasonable Phase-1 shape, but the survey suggests Phase 2 should evolve to
  the typed extractions in §7.2 (ActionItem / Decision / Commitment /
  OpenQuestion / Blocker) on a shared envelope, plus a separate `facts` /
  `entities` graph layer for connection-finding.
- BUILD_PLAN §6 Connector roadmap and Phase 2c (Cross-transcript relations) maps
  to the entity-fact graph in §9.1 above. The "co-occurrence first" minimal
  matches LightRAG dual-level retrieval; the "embeddings later" path matches the
  sqlite-vec primary in D8.
- IMPLEMENTATION_PLAN §G7 enrich.py map-reduce orchestration stays; the
  per-chunk schema-guided extraction in §9.2 is the *content* of those prompts,
  per `prompts.py` (G6).

This survey is meant to be the reference for the Phase 2 design conversation,
not a rewrite of Phase 1.

---

## 10. Decisions not made here

Things the survey deliberately did NOT settle (out of scope or genuinely
premature):

- **Permission/visibility design** — D-layer / 1.5 in BUILD_PLAN; survey
  doesn't touch it. Visibility/owner fields land at model time per
  IMPLEMENTATION_PLAN §D; enforcement at 1.5.
- **Dashboard visual design** — Phase 1d in BUILD_PLAN; orthogonal to
  knowledge-base architecture.
- **Real-time ingest** — explicitly out of scope (BUILD_PLAN §0, A2).
- **Standalone repo extraction** — open question per BUILD_PLAN §7.
- **Speaker voiceprint identity** — Layer 2 / §K extension point per
  IMPLEMENTATION_PLAN; this survey only addresses *name-level* resolution.
- **Cost/budget modeling** — needed before Phase 2 enrichment runs go on NearAI
  at scale; not in this survey's scope.

---

## Sources (consolidated)

**Chunking & extraction-from-text:**
- [Five Levels of Chunking Strategies in RAG (Kamradt notes)](https://medium.com/@anuragmishra_27746/five-levels-of-chunking-strategies-in-rag-notes-from-gregs-video-7b735895694d)
- [Dense X Retrieval / propositions (arXiv 2312.06648)](https://arxiv.org/abs/2312.06648) — [project page](https://chentong0.github.io/factoid-wiki/)
- [Late Chunking — Jina blog](https://jina.ai/news/late-chunking-in-long-context-embedding-models/) — [paper](https://arxiv.org/abs/2409.04701)
- [RAPTOR (arXiv 2401.18059)](https://arxiv.org/abs/2401.18059)
- [Anthropic Contextual Retrieval cookbook](https://platform.claude.com/cookbook/capabilities-contextual-embeddings-guide)
- [Action-Item-Driven Summarization of Long Meeting Transcripts (arXiv 2312.17581)](https://arxiv.org/abs/2312.17581)
- [Meeting Action Item Detection with Regularized Context Modeling (arXiv 2303.16763)](https://arxiv.org/pdf/2303.16763)
- [Gladia — Transcript to actionable notes pipeline](https://www.gladia.io/blog/transcript-to-actionable-notes-llm)
- [AWS — Meeting summarization & action items with Nova](https://aws.amazon.com/blogs/machine-learning/meeting-summarization-and-action-item-extraction-with-amazon-nova/)
- [Galileo — LLM summarization strategies](https://galileo.ai/blog/llm-summarization-strategies)
- [Speaker Turn Modeling for Dialogue Act Classification (arXiv 2109.05056)](https://arxiv.org/pdf/2109.05056)

**KG construction / GraphRAG family:**
- [GraphRAG paper (arXiv 2404.16130)](https://arxiv.org/abs/2404.16130) — [microsoft/graphrag](https://github.com/microsoft/graphrag)
- [LightRAG paper (arXiv 2410.05779)](https://arxiv.org/abs/2410.05779) — [HKUDS/LightRAG](https://github.com/HKUDS/LightRAG)
- [HippoRAG (arXiv 2405.14831)](https://arxiv.org/abs/2405.14831) — [HippoRAG 2 (arXiv 2502.14802)](https://arxiv.org/abs/2502.14802) — [OSU-NLP-Group/HippoRAG](https://github.com/OSU-NLP-Group/HippoRAG)
- [nano-graphrag](https://github.com/gusye1234/nano-graphrag)
- [Itext2KG (arXiv 2409.03284)](https://arxiv.org/abs/2409.03284) — [AuvaLab/itext2kg](https://github.com/AuvaLab/itext2kg)
- [LangChain LLMGraphTransformer docs](https://python.langchain.com/docs/how_to/graph_constructing/) — [Neo4j LLM-KG guide](https://neo4j.com/developer-blog/construct-knowledge-graphs-unstructured-text/)
- [REBEL (Babelscape — paper, EMNLP findings 2021)](https://aclanthology.org/2021.findings-emnlp.204/)
- [KG-Gen (arXiv 2502.09956)](https://arxiv.org/abs/2502.09956)
- [Entity resolution survey (arXiv 2402.06801)](https://arxiv.org/abs/2402.06801)

**Hybrid retrieval / vector stores / embedding models:**
- [Brenndoerfer — Hybrid Search BM25 + Dense + RRF](https://mbrenndoerfer.com/writing/hybrid-search-bm25-dense-retrieval-fusion)
- [Alex Garcia — sqlite-vec hybrid search](https://alexgarcia.xyz/blog/2024/sqlite-vec-hybrid-search/index.html)
- [ceaksan — FTS5 + Vector + RRF in SQLite](https://ceaksan.com/en/hybrid-search-fts5-vector-rrf)
- [AIngram — sqlite-vec + FTS5 agent memory](https://github.com/bozbuilds/AIngram)
- [liamca/sqlite-hybrid-search](https://github.com/liamca/sqlite-hybrid-search)
- [Sease — ColBERT in Practice](https://sease.io/2025/11/colbert-in-practice-bridging-research-and-industry.html)
- [Milvus — Vector Graph RAG without Graph DB](https://milvus.io/blog/vector-graph-rag-without-graph-database.md)
- [Neo4j — Advanced RAG Techniques](https://neo4j.com/blog/genai/advanced-rag-techniques/)
- [futureagi — Agentic RAG Guide 2026](https://futureagi.com/blog/agentic-rag-systems-2025/)
- [BEIR Benchmark (arXiv 2104.08663)](https://arxiv.org/pdf/2104.08663)
- [Morph — Ollama embedding models](https://www.morphllm.com/ollama-embedding-models)
- [BentoML — Open-source embedding models guide](https://www.bentoml.com/blog/a-guide-to-open-source-embedding-models)
- [Baseten — Best open-source embedding models](https://www.baseten.co/blog/the-best-open-source-embedding-models/)

**Meeting NLP / action items:**
- [AMI Meeting Corpus](https://groups.inf.ed.ac.uk/ami/corpus/)
- [Bui et al. 2009 — decision detection](https://aclanthology.org/W09-3934/)
- [Purver et al. 2007 — detecting decisions](https://aclanthology.org/W07-1623/)
- [Lampert et al. 2008 — commitments in email](https://aclanthology.org/I08-2113/)
- [MeetingBank — Hu et al. ACL 2023](https://aclanthology.org/2023.acl-long.906/)
- [QMSum — Zhong et al. NAACL 2021](https://aclanthology.org/2021.naacl-main.472/)
- [Cohan et al. EMNLP 2023 industry — action items](https://aclanthology.org/2023.emnlp-industry.71/)
- [Pereira et al. 2024 — modern LLM action items](https://arxiv.org/abs/2409.06044)
- [Wang et al. 2023 — unanswered questions](https://arxiv.org/abs/2305.04982)
- [Asher & Lascarides — Logics of Conversation (SDRT)](https://www.cambridge.org/core/books/logics-of-conversation/)
- [Fireflies — action items](https://fireflies.ai/blog/action-items)
- [Fellow API](https://fellow.app/api/)
- [Granola templates](https://www.granola.ai/templates)
- [Microsoft Teams Intelligent Recap](https://learn.microsoft.com/en-us/microsoftteams/intelligent-recap)
- [Microsoft Graph aiInsight resource](https://learn.microsoft.com/en-us/graph/api/resources/aiinsight)
- [Google Meet — Take notes for me](https://support.google.com/meet/answer/14754931)

**Agent memory systems:**
- [Mem0 paper (arXiv 2504.19413)](https://arxiv.org/html/2504.19413v1) — [State of Memory 2026](https://mem0.ai/blog/state-of-ai-agent-memory-2026)
- [Zep paper (arXiv 2501.13956)](https://arxiv.org/html/2501.13956v1) — [Graphiti / Neo4j writeup](https://neo4j.com/blog/developer/graphiti-knowledge-graph-memory/)
- [A-MEM paper (arXiv 2502.12110)](https://arxiv.org/html/2502.12110v11) — [agiresearch/a-mem](https://github.com/agiresearch/a-mem)
- [Letta concepts docs](https://docs.letta.com/concepts/letta/) — [Letta/MemGPT walkthrough](https://sureprompts.com/blog/letta-memgpt-walkthrough)
- [LangGraph memory docs](https://docs.langchain.com/oss/python/langgraph/memory) — [LangMem](https://langchain-ai.github.io/langmem/concepts/conceptual_guide/)
- [Generative Agents (Park 2023, arXiv 2304.03442)](https://ar5iv.labs.arxiv.org/html/2304.03442)
- [OpenAI Memory FAQ](https://help.openai.com/en/articles/8590148-memory-faq)
- [AutoGen Teachability / ChromaDB memory](https://microsoft.github.io/autogen/dev//reference/python/autogen_ext.memory.chromadb.html)
- [LongMemEval benchmark](https://github.com/xiaowu0162/longmemeval)
