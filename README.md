# guru
*I was sent out from the power and have come to you who study me and am found by you who seek me.*

Cross-tradition esoteric and religious text analysis engine. Guru ingests primary texts from multiple spiritual traditions, builds a concept graph capturing thematic overlaps, and uses hybrid RAG (vector similarity + graph traversal) to answer questions with traceable, per-tradition citations.

```
$ guru query "How does the concept of divine light appear across traditions?"

[Gnosticism | Gospel of Thomas | Logion 77]
"I am the light that is over all things. Split a piece of wood, and I am there.
Lift up a stone, and you will find me there."

[Jewish Mysticism | Sefer Yetzirah | Section 1a]
"He carved and created His World in Thirty-Two Wondrous Ways of Wisdom...
Ten SEFIROT BELIMAH — their visage is as the look of lightning."

Sources: 4 chunks from gnosticism, jewish_mysticism | Model: Carnice-27b-Q4_K_M.gguf | Elapsed: 118.3s
```

---

## How It Works

Guru combines two retrieval strategies that compensate for each other's weaknesses:

**Vector search** finds chunks that are semantically similar to the query. Good at surface-level matching, but misses cases where different traditions use completely different vocabulary for the same idea.

**Concept graph traversal** follows explicit edges between concepts across traditions. Knows that Gnostic *pleroma*, Kabbalistic *ein sof*, and Neoplatonic *the One* are related even though they share zero tokens. Edges carry confidence tiers (✓ Verified / ◇ Proposed / ~ Inferred) so the model hedges appropriately.

Both paths merge, re-rank for tradition diversity, and inject into a prompt with mandatory citation rules. The model may not fabricate citations or reference traditions outside the active scope.

---

## Project Structure

```
guru/
├── config/                   # model.toml, embedding.toml
├── concepts/
│   └── taxonomy.toml         # 44 hand-curated concepts across 6 categories
├── sources/
│   └── manifest.toml         # 22 v1 source texts with download URLs
├── chunking/                 # per-text chunking strategy configs
├── raw/                      # downloaded source texts (git-ignored)
├── corpus/                   # chunked texts + metadata TOML (git-tracked)
├── data/                     # guru.db (SQLite graph) + vectordb/ (git-ignored)
├── scripts/                  # pipeline scripts
├── guru/                     # runtime library (retriever, prompt, model, cli)
└── tests/                    # 35 tests
```

---

## Setup

```bash
git clone <repo-url> && cd guru
pip install chromadb tiktoken requests beautifulsoup4 tomli-w numpy
```

Requires Python 3.11+. For LLM inference, point `config/model.toml` at whichever
provider you have (see Configuration below). Embeddings default to
`ollama/nomic-embed-text` at `localhost:11434` — run `ollama pull nomic-embed-text`
once to have it available.

---

## Running the Pipeline

The build runs in five stages. Each stage produces artifacts consumed by the next.

```bash
# Stage 1 — Download source texts
python scripts/acquire.py

# Stage 2 — Chunk into citation-addressable units
python scripts/chunk.py

# Stage 3 — Build concept graph (bootstrap + LLM tagging)
python scripts/graph_bootstrap.py
python scripts/tag_concepts.py --provider llamacpp --model Carnice-27b-Q4_K_M.gguf

# Stage 4 — Embed chunks into vector store
python scripts/embed_corpus.py

# Stage 3 (cont.) — Cross-tradition edge proposals (requires embeddings)
python scripts/propose_edges.py --provider llamacpp --model Carnice-27b-Q4_K_M.gguf

# Stage 3 (cont.) — Backfill accepted concept tags into vector metadata
python scripts/backfill_concepts.py
```

---

## Review CLIs

Stage 3 produces staged tags and edge proposals that need human review before
they are promoted to the live graph. Both tools are interactive terminal UIs.

### `python scripts/review_tags.py` — Concept tag review

Reviews LLM-proposed concept tags (chunk → concept associations) from `staged_tags`.
Accepted tags with score ≥ 2 are promoted to live `EXPRESSES` edges in `guru.db`.

```
$ python scripts/review_tags.py [--tradition gnosticism] [--text gospel-of-thomas]
                                 [--concept gnosis_direct_knowledge] [--min-score 2]

======================================================================
CHUNK:   gnosticism.gospel-of-thomas.001
SECTION: Gospel of Thomas — Logion 1
----------------------------------------------------------------------
BODY:    And he said, "Whoever finds the interpretation of these
         sayings will not experience death."
----------------------------------------------------------------------
CONCEPT: gnosis_direct_knowledge
DEF:     Salvation through direct experiential knowledge of the
         divine nature, not through faith, ritual, or moral works alone.
SCORE:   3/3
LLM:     Logion 1 directly equates finding the interpretation with
         escaping death — salvation through knowledge.
----------------------------------------------------------------------
Action [a/r/s/c/q]:
```

Keys: **a** accept → promotes to live EXPRESSES edge | **r** reject | **s** skip | **c** reassign to different concept | **q** quit

---

### `python scripts/review_edges.py` — Cross-tradition edge review

Reviews LLM-proposed cross-tradition relationships from `staged_edges`.
Accepted edges are promoted to the live `edges` table in `guru.db`.

```
$ python scripts/review_edges.py [--edge-type PARALLELS] [--min-confidence 0.7]
                                  [--tradition-a gnosticism] [--tradition-b jewish_mysticism]

======================================================================
EDGE:   PARALLELS  (conf=0.85)
LLM:    Both passages describe divine light as immanent throughout
        creation — Thomas places it within wood and stone; Sefer
        Yetzirah places it in every direction through the Sefirot.
----------------------------------------------------------------------
A: Gnosticism | Gospel of Thomas    B: Jewish Mysticism | Sefer Yetzirah
It is I who am the light which      He carved and created His World in
is above them all. Split a piece    Thirty-Two Wondrous Ways of Wisdom...
of wood, and I am there...          Ten SEFIROT BELIMAH — their visage
                                    is as the look of lightning...
----------------------------------------------------------------------
Action [a/p/r/c/s/q]:
```

Keys: **a** accept as verified | **p** accept as proposed | **r** reject | **c** reclassify edge type | **s** skip | **q** quit

---

## Querying

### Single query

```bash
python -m guru query "What is the role of divine light in Gnostic thought?"
```

### With tradition filters

```bash
# Only search Gnosticism and Hermeticism
python -m guru query "What is the demiurge?" --tradition gnosticism hermeticism

# Exclude a tradition
python -m guru query "What is enlightenment?" --exclude-tradition buddhism
```

### Interactive session

```bash
python -m guru interactive
python -m guru interactive --tradition gnosticism jewish_mysticism
```

### Verbose mode (shows retrieval details)

```bash
python -m guru query "What is gnosis?" --verbose
# Prints retrieved chunks with similarity scores and tier labels before the response
```

---

## Configuration

**`config/model.toml`** — LLM provider, retrieval tuning, and re-ranking weights:

```toml
[provider]
name = "llamacpp"                    # llamacpp | ollama | anthropic | openai
model = "Carnice-27b-Q4_K_M.gguf"
llamacpp_url = "http://127.0.0.1:8080"
max_tokens = 2048

[retrieval]
top_k = 10
min_similarity = 0.50
max_per_tradition = 3               # tradition diversity cap

[ranking]
tier_verified  = 1.0
tier_proposed  = 0.7
tier_inferred  = 0.4
diversity_boost = 0.1
```

**`config/embedding.toml`** — Embedding model and vector store:

```toml
[model]
provider = "ollama"                  # ollama | sentence_transformers | api
model_name = "nomic-embed-text"
dimensions = 768

[backend]
type = "chromadb"                    # chromadb | qdrant
chroma_path = "data/vectordb"
collection_name = "guru_corpus"
```

---

## LLM Providers

All pipeline scripts (`tag_concepts.py`, `propose_edges.py`) and the query CLI
share the same provider abstraction in `scripts/llm.py`.

| Provider | How to use |
|---|---|
| `llamacpp` | llama.cpp server running at `config/model.toml → llamacpp_url`. Zero extra dependencies — uses raw HTTP. Handles thinking models (reasoning_content fallback). |
| `ollama` | Ollama running locally. `--provider ollama --model qwen3:8b` |
| `anthropic` | `pip install anthropic`. Set `ANTHROPIC_API_KEY`. |
| `openai` | `pip install openai`. Set `OPENAI_API_KEY`. |

---

## Starter Corpus (v1)

| Tradition | Texts |
|---|---|
| Gnosticism | Gospel of Thomas, Gospel of Philip |
| Hermeticism | Corpus Hermeticum I–XVII |
| Jewish Mysticism | Sefer Yetzirah, Zohar (selections) |
| Buddhism | Heart Sutra |

Additional traditions (Vedanta, Neoplatonism, Sufism, Taoism, Christian Mysticism)
are in `sources/manifest.toml` — sources currently 404; URL updates pending.

---

## Testing

```bash
# All tests (35)
python -m pytest tests/ -v

# Individual suites
python -m pytest tests/test_citations.py      # citation format + real corpus
python -m pytest tests/test_preferences.py    # filter logic + no-leak
PYTHONPATH=scripts/chunkers python -m pytest tests/test_chunking.py  # chunk round-trip
python -m pytest tests/test_retrieval.py      # e2e retrieval (requires Ollama)
```

---

## Docs

- [`docs/chunking-schema.md`](docs/chunking-schema.md) — Chunking config format for all three splitter strategies
- [`docs/benchmark-stage4.md`](docs/benchmark-stage4.md) — Embedding throughput and retrieval latency measurements
- [`docs/guru-implementation.md`](docs/guru-implementation.md) — Full implementation design (42 tasks, 5 stages)

---

## License

MIT
