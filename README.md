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

Sources: 4 chunks from gnosticism, jewish_mysticism | Model: Qwen3.5-27B-UD-Q4_K_XL.gguf | Elapsed: 118.3s
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
│   └── taxonomy.toml         # 158 concepts in a 3-tier domain→family→concept hierarchy
├── sources/
│   └── manifest.toml         # ~120 source texts across 21 traditions
├── chunking/                 # per-text chunking strategy configs
├── raw/                      # downloaded source texts (git-ignored)
├── corpus/                   # chunked texts + metadata TOML (git-tracked, ~4,400 chunks)
├── data/                     # guru.db (SQLite graph + embeddings, git-ignored)
├── scripts/                  # pipeline scripts
├── guru/                     # runtime library (retriever, prompt, model, cli)
└── tests/                    # ~264 tests
```

---

## Setup

```bash
git clone <repo-url> && cd guru
pip install tiktoken requests beautifulsoup4 tomli-w numpy
```

Requires Python 3.11+. For LLM inference, point `config/model.toml` at whichever
provider you have (see Configuration below). Embeddings default to
`ollama/nomic-embed-text` at `localhost:11434` — run `ollama pull nomic-embed-text`
once to have it available. All vector storage is SQLite (`data/guru.db`
chunk_embeddings table); no separate vector DB is needed.

### Optional: derive_parallels / EDGE_RERANK (torch + transformers)

`scripts/derive_parallels.py` and the `EDGE_RERANK` query-time path both go
through `guru.rerank.score_pairs`, which lazy-imports torch + transformers
only when that code actually runs — the rest of the pipeline (chunking,
tagging, retrieval) stays torch-free. Install this group only if you run
either:

```bash
uv venv                                                              # .venv/, gitignored
uv pip install -r requirements-derive.txt --index-strategy unsafe-best-match
```

Then invoke those two paths with `.venv/bin/python` explicitly — a bare
`python3` will get partway through a run and die inside `guru.rerank._load()`,
after the database and taxonomy have already loaded.

The pins are CPU-only on purpose: `guru/rerank.py` does no device placement, so
this code cannot use a GPU, and the default PyPI torch would add ~6 GB of
`nvidia-*` wheels it can never touch. The CPU build installs in 901 MB. See the
header of `requirements-derive.txt` for why the `--index-strategy` flag is not
optional.

No other script in the repo touches this dependency.

### Model home

All guru fine-tunes are vendored under `~/programs/guru/<purpose>-v<N>/`
(siblings of `~/programs/mistral`, `~/programs/gemma4` — never inside a repo
checkout). The repo pins the path (and, where computed, a sha256 of the
weights file) in config or in the serving script; a `training-card.json` (or
`training-card.md`/README equivalent) ships alongside the weights for
provenance. Current: `~/programs/guru/scorer-v1` (the 22.7M thin
(query,chunk) relevance scorer used by `derive_parallels`, pinned in
`config/derived_parallels.toml`) and `~/programs/guru/4b-v3` (the
`qwen-3-4b-guru` v3-r32 tagger, served by `scripts/run-qwen-4b-guru.sh`).

---

## Running the Pipeline

The build runs in five stages. Each stage produces artifacts consumed by the next.

```bash
# Stage 1 — Download source texts
python scripts/acquire.py

# Stage 2 — Chunk into citation-addressable units
python scripts/chunk.py

# Stage 3 — Build concept graph
python scripts/graph_bootstrap.py    # tradition + chunk nodes, BELONGS_TO edges
python scripts/sync_taxonomy.py      # concept/family nodes from taxonomy.toml
python scripts/tag_concepts.py --provider llamacpp --model Qwen3.5-27B-UD-Q4_K_XL.gguf

# Stage 4 — Embed chunks into vector store
python scripts/embed_corpus.py

# Cross-tradition PARALLELS are no longer proposed and reviewed (Pass C is
# retired). They are derived corpus-wide from applied tags by node 16 —
# see docs/ingest/16-derive-parallels.md:
OMP_NUM_THREADS=8 .venv/bin/python scripts/derive_parallels.py
```

---

## Reviewing staged tags

Stage 3 produces staged tags that need human review before they are promoted to
the live graph. Queuing accept / reject / reassign decisions and applying them
is done through the **guru-review web app** (its HTTP API; the `guru-review-tags`
skill drives it). The terminal tool below is **read-only** — it shows what is
pending so you can read the chunk bodies, but it never writes.

(Cross-tradition edge proposals — Pass C — are retired; PARALLELS are derived at
node 16 instead, with no review step, so there is no edge-review CLI.)

### `python scripts/view_staged_tags.py` — view pending concept tags

Lists LLM-proposed concept tags (chunk → concept associations) from `staged_tags`
with full context — chunk body, concept, primary family, definition, score, and
the tagger's justification.

```
$ python scripts/view_staged_tags.py [--tradition gnosticism] [--text gospel-of-thomas]
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
```

Queue accept / reject / reassign decisions in the guru-review web app, not here.

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
model = "Qwen3.5-27B-UD-Q4_K_XL.gguf"
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

**`config/embedding.toml`** — Embedding model. Vectors land in the
`chunk_embeddings` table inside `data/guru.db`; there is no separate
vector store to configure.

```toml
[model]
provider = "ollama"                  # ollama | sentence_transformers | api
model_name = "nomic-embed-text"
dimensions = 768
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

## Corpus

21 traditions, ~120 public-domain source texts, ~4,400 citation-addressable chunks.
Representative texts per tradition (full list in `sources/manifest.toml`):

| Tradition | Texts |
|---|---|
| Gnosticism | Gospel of Thomas, Gospel of Philip, Pistis Sophia (Horner) |
| Mandaean | Gnostic John the Baptizer (Sidra d'Yahya extracts) |
| Hermeticism | Corpus Hermeticum I–XVII |
| Jewish Mysticism | Sefer Yetzirah, Zohar selections, 1 Enoch |
| Christian Mysticism | Boehme (Life & Doctrines), Meister Eckhart's Sermons |
| Buddhism | Diamond Sutra, Heart Sutra |
| Platonism | Plato: Symposium, Phaedo, Republic, Timaeus |
| Neoplatonism | Plotinus: Enneads (Taylor) |
| Greek Mystery | Orphic Hymns, Pythagorean Golden Verses |
| Renaissance Hermeticism | Bruno: The Heroic Enthusiasts |
| Western Esoteric | Ouspensky: Tertium Organum |
| Sufism | Rumi: Masnavi (Book I) |
| Taoism | Tao Te Ching, Zhuangzi (Inner Chapters) |
| Zoroastrianism | Gathas, Bundahishn |
| Egyptian | Book of the Dead, Egyptian Heaven and Hell |
| Mesopotamian | Enuma Elish, Descent of Ishtar |
| Upanishads | Isa, with bulk acquisition deferred |
| Norse | Poetic Edda (Hávamál, Völuspá) |
| Celtic | The Mabinogion |
| Finnic | The Kalevala |
| Shinto | Kojiki (Beginning of Heaven and Earth) |

Sources are public-domain (mostly sacred-texts.com, gnosis.org, ccel.org, gutenberg.org).
Pipeline data is regenerated by `scripts/chunk.py` — review the chunker configs, not
the generated `corpus/*.toml` (marked `linguist-generated` so GitHub collapses them).

---

## Testing

```bash
# All tests
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
