# guru
I was sent out from the power and have come to you who study me and am found by you who seek me.


Cross-tradition esoteric and religious text analysis engine. Guru ingests primary texts from multiple spiritual traditions, builds a concept graph capturing thematic overlaps, and uses hybrid RAG (vector similarity + graph traversal) to answer questions with traceable citations.

```
"How does the concept of divine spark appear across traditions?"

[Gnosticism | Gospel of Thomas | Logion 77]
"I am the light that is over all things."

[Vedanta | Chandogya Upanishad | 6.8.7]
The refrain "tat tvam asi" identifies the individual atman with Brahman...

[Hermeticism | Corpus Hermeticum | Tractate I.6]
The Poimandres describes the divine Light as the origin of the human nous...
```

## How It Works

Guru combines two retrieval strategies that compensate for each other's weaknesses:

**Vector search** finds chunks that are semantically similar to the query. Good at surface-level matching, but struggles when different traditions use completely different vocabularies for the same idea.

**Concept graph traversal** follows explicit edges between concepts across traditions. Knows that Gnostic "pleroma," Kabbalistic "ein sof," and Neoplatonic "the One" are related — even though they share zero tokens. Edges are tagged with confidence tiers (◆ Verified, ◇ Proposed, ○ Inferred) so the agent can hedge appropriately.

Results from both paths are merged, re-ranked for tradition diversity, and injected into a prompt with mandated citation rules.

## Project Structure

```
guru/
├── config/                   # Model and embedding configuration
├── concepts/                 # Hand-curated concept taxonomy
│   └── taxonomy.toml
├── sources/                  # Download manifest for raw texts
│   └── manifest.toml
├── chunking/                 # Per-text chunking rules
├── raw/                      # Downloaded source texts (git-ignored)
├── corpus/                   # Chunked texts with metadata (git-tracked)
├── data/                     # SQLite graph + vector store (git-ignored)
├── scripts/                  # Pipeline scripts (acquire, chunk, tag, embed)
├── guru/                     # Runtime library (retriever, prompt, model, cli)
└── tests/
```

## Setup

```bash
git clone <repo-url> && cd guru
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

For LLM providers (install whichever you plan to use):

```bash
pip install -e ".[anthropic]"    # Anthropic API
pip install -e ".[openai]"       # OpenAI API
# Ollama: just have it running locally, no extra pip dependency
```

## Pipeline

The build runs in five stages. Each stage produces artifacts consumed by the next.

```bash
# Stage 1: Download source texts
python scripts/acquire.py

# Stage 2: Chunk into citation-addressable units
python scripts/chunk.py

# Stage 3: Build concept graph
python scripts/graph_bootstrap.py                      # schema + nodes
python scripts/tag_concepts.py --model qwen3:8b        # LLM-assisted tagging
python scripts/review_tags.py                          # human review (CLI)

# Stage 4: Embed chunks into vector store
python scripts/embed_corpus.py

# Stage 3 (cont): Cross-tradition edge proposals (needs embeddings)
python scripts/propose_edges.py --model qwen3:8b
python scripts/review_edges.py                         # human review (CLI)

# Stage 4 (cont): Backfill concept metadata into vectors
python scripts/backfill_concepts.py

# Stage 5: Query
guru query "What parallels exist between Gnostic aeons and Kabbalistic sefirot?"
```

## Configuration

**`config/model.toml`** — LLM provider and retrieval tuning:

```toml
[model]
provider = "ollama"        # ollama | anthropic | openai
model_name = "qwen3:8b"
temperature = 0.3

[retrieval]
top_k = 15
diversity_boost = 1.3
```

**`config/embedding.toml`** — Embedding model and vector store:

```toml
[model]
provider = "ollama"
model_name = "nomic-embed-text"

[vector_store]
backend = "chromadb"
persist_directory = "./data/vectordb"
```

## Tradition Scope

Users configure which traditions and texts are active. The full corpus is always available; preferences filter what the retriever can see.

```toml
# user_preferences.toml
[scope]
mode = "blacklist"

[scope.blacklist]
traditions = []
texts = ["sufism.al-hallaj"]
```

## Starter Corpus (v1)

Gnosticism (Nag Hammadi), Kabbalah (Sefer Yetzirah, Zohar), Hermeticism (Corpus Hermeticum), Neoplatonism (Enneads), Vedanta (Upanishads), Buddhism (Heart Sutra, Pali Canon), Christian Mysticism (Eckhart, Pseudo-Dionysius), Sufism (Ibn Arabi, Rumi), Taoism (Tao Te Ching, Chuang Tzu).

## Docs

- [`guru-architecture.md`](docs/guru-architecture.md) — Full architecture document (concept graph design, extensibility, token economy, hosted platform)
- [`guru-implementation.md`](docs/guru-implementation.md) — Implementation design with task breakdown (42 tasks across 5 stages)

## License

TBD
