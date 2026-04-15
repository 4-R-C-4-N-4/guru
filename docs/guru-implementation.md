# Guru — Core Pipeline Implementation Design

## Document Purpose

This document breaks down the Guru core pipeline into concrete implementation tasks, from raw text acquisition through a working RAG-powered agent. It covers five pipeline stages: corpus acquisition, chunking, concept graph construction, vector indexing, and model integration. Each stage is specified with inputs, outputs, data formats, scripts to build, and acceptance criteria.

This is the foundation build. The hosted platform, token economy, and community curation layers (see `guru-architecture.md` Sections 4.7+) come after this pipeline is proven end-to-end.

---

## Pipeline Overview

```
 ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐
 │  STAGE 1 │───►│  STAGE 2 │───►│  STAGE 3 │───►│  STAGE 4 │───►│  STAGE 5 │
 │ Acquire  │    │  Chunk   │    │  Graph   │    │  Index   │    │  Serve   │
 │          │    │          │    │          │    │          │    │          │
 │ Download │    │ Segment  │    │ Tag      │    │ Embed    │    │ Retrieve │
 │ texts    │    │ into     │    │ concepts │    │ chunks   │    │ + prompt │
 │ from     │    │ citation-│    │ + create │    │ into     │    │ + answer │
 │ sources  │    │ addressable│   │ edges    │    │ vector   │    │ with     │
 │          │    │ chunks   │    │          │    │ store    │    │ citations│
 └──────────┘    └──────────┘    └──────────┘    └──────────┘    └──────────┘
     raw/            corpus/         guru.db          guru.db        runtime
     *.html          **/*.toml       (SQLite)         + vectordb
     *.txt
```

---

## Stage 1: Corpus Acquisition

### Goal

Download and normalize raw source texts into a clean plaintext format, one file per text, with provenance metadata recorded.

### Source Registry

All sources are tracked in a manifest file that records where each text came from, its license status, and download instructions.

```toml
# sources/manifest.toml

[[source]]
id = "gospel-of-thomas"
tradition = "gnosticism"
label = "Gospel of Thomas (Lambdin translation)"
url = "http://gnosis.org/naghamm/gthlamb.html"
format = "html"
license = "public_domain"
translator = "Thomas O. Lambdin"
notes = "Full Coptic-to-English translation. Scrape main content div."

[[source]]
id = "corpus-hermeticum"
tradition = "hermeticism"
label = "Corpus Hermeticum (Mead translation)"
url = "https://www.sacred-texts.com/chr/herm/index.htm"
format = "html_multi"  # multiple pages, one per tractate
license = "public_domain"
translator = "G.R.S. Mead"
notes = "Index page links to individual tractates. Scrape each."

[[source]]
id = "heart-sutra"
tradition = "buddhism"
label = "Heart Sutra (Conze translation)"
url = "https://www.sacred-texts.com/bud/index.htm"
format = "html"
license = "public_domain"
translator = "Edward Conze"
```

### Scripts to Build

**`scripts/acquire.py`** — Main acquisition driver.

- Reads `sources/manifest.toml`
- For each source, dispatches to the appropriate downloader based on `format`:
  - `html` — single page fetch + BeautifulSoup extraction
  - `html_multi` — follow index links, fetch each page, extract content
  - `text` — direct download
  - `sefaria_api` — hit Sefaria's public API for Jewish texts
- Outputs cleaned plaintext to `raw/{tradition}/{text_id}.txt`
- Writes `raw/{tradition}/{text_id}.meta.toml` with download timestamp, source URL, SHA256 of content

**`scripts/downloaders/`** — Per-source-type download modules.

- `sacred_texts.py` — handles sacred-texts.com HTML structure (strip navigation, footnotes, ads)
- `gnosis_org.py` — handles gnosis.org Nag Hammadi pages
- `sefaria.py` — wraps Sefaria API for Sefer Yetzirah, Zohar selections
- `access_to_insight.py` — handles accesstoinsight.org Pali Canon pages
- `generic_html.py` — fallback for simple single-page extractions

### Output Format

```
raw/
├── gnosticism/
│   ├── gospel-of-thomas.txt          # clean plaintext
│   ├── gospel-of-thomas.meta.toml    # provenance
│   ├── gospel-of-philip.txt
│   ├── gospel-of-philip.meta.toml
│   └── ...
├── hermeticism/
│   ├── corpus-hermeticum-01.txt      # one file per tractate
│   ├── corpus-hermeticum-01.meta.toml
│   └── ...
└── ...
```

```toml
# raw/gnosticism/gospel-of-thomas.meta.toml
[provenance]
source_url = "http://gnosis.org/naghamm/gthlamb.html"
downloaded_at = "2026-04-15T12:00:00Z"
content_sha256 = "a1b2c3..."
format = "html"
extractor = "gnosis_org"
license = "public_domain"
translator = "Thomas O. Lambdin"
```

### Acceptance Criteria

- [ ] Every source in `manifest.toml` has a corresponding file in `raw/`
- [ ] All HTML artifacts (navigation, scripts, styling) are stripped
- [ ] Plaintext is UTF-8 normalized, no mojibake
- [ ] Provenance metadata is complete (URL, timestamp, hash) for every file
- [ ] Running `acquire.py` twice produces identical output (idempotent — skips already-downloaded files by hash comparison)

### Tasks

```
1.1  Create sources/manifest.toml with all v1 sources
1.2  Build generic_html.py downloader (BeautifulSoup extraction)
1.3  Build sacred_texts.py downloader (handles their specific HTML layout)
1.4  Build gnosis_org.py downloader
1.5  Build sefaria.py downloader (API client for Jewish texts)
1.6  Build access_to_insight.py downloader
1.7  Build acquire.py orchestrator (reads manifest, dispatches, writes raw/)
1.8  QA pass: manually verify 1 text per tradition against source
```

---

## Stage 2: Chunking

### Goal

Segment raw texts into citation-addressable chunks that respect the natural structure of each document. Every chunk must carry enough metadata to produce a full `[Tradition | Text | Section]` citation.

### Chunking Rules

Chunks follow the natural divisions of each text type. The chunker never splits mid-thought.

| Text Type | Natural Unit | Chunk Granularity | Example |
|-----------|-------------|-------------------|---------|
| Sayings gospel | Logion / saying | 1 logion per chunk | Gospel of Thomas, Logion 77 |
| Tractate | Numbered section or chapter | 1 section per chunk (split if >800 tokens) | Corpus Hermeticum, Tractate I, Section 3 |
| Sutra | Verse or numbered passage | 1-5 verses per chunk (group by theme) | Heart Sutra, Verse 12-14 |
| Ennead | Tractate + section number | 1 section per chunk | Enneads V.2.1 |
| Kabbalistic | Chapter + verse/mishnah | 1 mishnah or passage per chunk | Sefer Yetzirah 1:1 |
| Sermons | Paragraph groupings | 2-4 paragraphs per chunk | Eckhart, Sermon 52 |
| Poetry | Stanza or named section | 1-3 stanzas per chunk | Tao Te Ching, Chapter 1 |

**Token budget:** 200–800 tokens per chunk. If a natural unit exceeds 800 tokens, split at the nearest paragraph boundary and note the sub-section in the chunk ID (e.g., `neoplatonism.enneads.V-2-1a`, `V-2-1b`).

### Scripts to Build

**`scripts/chunk.py`** — Main chunking driver.

- Reads raw text files from `raw/`
- Loads chunking rules from a per-text config: `chunking/{tradition}/{text_id}.toml`
- Applies the appropriate splitter (regex-based section detection, or line-count-based for unstructured texts)
- Writes TOML chunks to `corpus/{tradition}/{text_id}/chunks/`
- Writes `corpus/{tradition}/{text_id}/metadata.toml` with text-level metadata

**`chunking/` configs** — Per-text chunking instructions.

```toml
# chunking/gnosticism/gospel-of-thomas.toml

[chunking]
strategy = "regex"
pattern = '(?:^|\n)\(?(\d+)\)\s+'   # matches "(1) Jesus said..." logion markers
section_label_format = "Logion {n}"
max_tokens = 800
group_size = 1                        # 1 logion per chunk (some texts may group 3-5 verses)

[metadata]
tradition = "Gnosticism"
text_name = "Gospel of Thomas"
translator = "Thomas O. Lambdin"
sections_format = "logion"
```

```toml
# chunking/hermeticism/corpus-hermeticum.toml

[chunking]
strategy = "heading"
heading_pattern = '^\d+\.\s+'         # matches "1. " section numbers
section_label_format = "Section {n}"
max_tokens = 800
group_size = 1

[metadata]
tradition = "Hermeticism"
text_name = "Corpus Hermeticum"
translator = "G.R.S. Mead"
sections_format = "tractate.section"
```

### Output Format

TOML chunks as specified in the architecture doc:

```toml
# corpus/gnosticism/gospel-of-thomas/chunks/013.toml

[chunk]
id = "gnosticism.gospel-of-thomas.013"
tradition = "Gnosticism"
text_name = "Gospel of Thomas"
section = "Logion 77"
translator = "Thomas O. Lambdin"
source_url = "http://gnosis.org/naghamm/gthlamb.html"
token_count = 62

[content]
body = """
Jesus said, "I am the light that is over all things.
I am all: from me all came forth, and to me all attained.
Split a piece of wood; I am there.
Lift up the stone, and you will find me there."
"""

[annotations]
# Empty at this stage — populated in Stage 3
concepts = []
related_chunks = []
```

### Acceptance Criteria

- [ ] Every raw text file produces at least one chunk
- [ ] No chunk exceeds 800 tokens
- [ ] No chunk is split mid-sentence
- [ ] Every chunk has a valid `section` field that matches the text's native division system
- [ ] Chunk IDs are unique across the entire corpus
- [ ] Round-trip test: concatenating all chunks for a text reconstructs the original content (minus whitespace normalization)

### Tasks

```
2.1  Define chunking config schema (chunking/*.toml)
2.2  Write chunking configs for all v1 texts (one per text)
2.3  Build regex-based splitter (for logion/verse/numbered texts)
2.4  Build heading-based splitter (for tractate/section texts)
2.5  Build paragraph-grouping splitter (for prose texts like sermons)
2.6  Build chunk.py orchestrator (reads raw/, applies configs, writes corpus/)
2.7  Build token counter (tiktoken or equivalent, used to enforce 800-token budget)
2.8  Write corpus/traditions.toml registry from chunking configs
2.9  QA pass: verify chunk boundaries for 2-3 texts per tradition
2.10 Round-trip test: verify chunk concatenation matches raw source
```

---

## Stage 3: Concept Graph Construction

### Goal

Build the SQLite concept graph with three node types (concept, chunk, tradition) and five edge types. Populate it using a combination of hand-curated taxonomy, LLM-assisted tagging, and human review.

### Sub-stages

This stage has three distinct passes, each building on the previous:

```
Pass A: Bootstrap           Pass B: LLM Tagging          Pass C: Edge Proposal
─────────────────           ───────────────────          ────────────────────
Create DB schema            For each chunk:              For high-similarity
Insert tradition nodes      Score against taxonomy       chunk pairs across
Insert concept nodes        Propose new concepts         traditions:
(hand-curated taxonomy)     Write to staging table       LLM classifies
                            Human review pass            relationship
                            Promote accepted tags        Write proposed edges
                            to EXPRESSES edges           Human review pass
                                                         Promote to graph
```

### Pass A: Bootstrap

**`scripts/graph_bootstrap.py`**

- Creates SQLite database `guru.db` with schema from architecture doc
- Inserts tradition nodes from `corpus/traditions.toml`
- Inserts concept nodes from `concepts/taxonomy.toml` (hand-curated starter taxonomy)
- Inserts chunk nodes from `corpus/**/*.toml` with BELONGS_TO edges to their tradition

**`concepts/taxonomy.toml`** — The hand-curated concept vocabulary:

```toml
[concepts.cosmology]
emanation_hierarchy = "A chain of divine beings or principles flowing from a single transcendent source"
demiurge = "A secondary creator deity, often ignorant or malevolent, responsible for the material world"
pleroma_fullness = "The totality or fullness of the divine realm, containing all aeons or emanations"
divine_spark = "A fragment of divine light or consciousness trapped within material existence"
cyclical_cosmology = "The universe undergoes repeated cycles of creation, dissolution, and recreation"
creation_ex_nihilo = "Creation of the world from nothing by an act of divine will"
maya_illusion = "The material world as illusion or veil obscuring ultimate reality"
dependent_origination = "All phenomena arise through interdependent conditions, with no independent existence"

[concepts.soteriology]
gnosis_direct_knowledge = "Salvation through direct experiential knowledge of the divine, not faith or works"
ego_death = "Dissolution of the individual self as a prerequisite for spiritual awakening"
theosis_deification = "The human being becomes divine or participates in divine nature"
liberation_moksha = "Release from the cycle of rebirth and suffering"
bodhisattva_path = "Delaying personal liberation to assist all beings in attaining enlightenment"
via_negativa = "Approaching the divine by negation — describing what God is not"
divine_union = "Mystical merger of the individual soul with the divine ground"

[concepts.theology]
apophatic_theology = "God can only be described by what God is not; all positive attributes are inadequate"
divine_immanence = "The divine is present within all things, not separate from creation"
divine_transcendence = "The divine is utterly beyond and apart from the created world"
divine_feminine = "The feminine as a primary expression or aspect of the divine"
logos_word = "A divine ordering principle or creative utterance through which the world is structured"
light_metaphor = "Light as a symbol for divine presence, knowledge, or consciousness"
unity_of_being = "All existence is ultimately one substance or one divine reality"

[concepts.praxis]
meditation_contemplation = "Sustained inward attention as a means of spiritual realization"
ascetic_practice = "Disciplining the body through renunciation to purify the soul"
ritual_theurgy = "Ritual acts that invoke or channel divine power for spiritual transformation"
sacred_sound_mantra = "Specific sounds or words that carry intrinsic spiritual power"
dream_vision = "Dreams or visionary states as channels for divine communication"
```

### Pass B: LLM-Assisted Concept Tagging

**`scripts/tag_concepts.py`**

- Iterates over all chunks in `corpus/`
- For each chunk, sends the structured scoring prompt (see architecture doc Section 4.6.1) to an LLM
- Writes results to `guru.db` staging tables:

```sql
CREATE TABLE staged_tags (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id        TEXT NOT NULL,
    concept_id      TEXT NOT NULL,       -- existing concept or proposed new concept
    score           INTEGER NOT NULL,    -- 0-3
    justification   TEXT,
    is_new_concept  BOOLEAN DEFAULT FALSE,
    new_concept_def TEXT,                -- definition if proposing new concept
    status          TEXT DEFAULT 'pending',  -- pending | accepted | rejected
    reviewed_by     TEXT,
    reviewed_at     TIMESTAMP
);
```

- LLM configuration is externalized — the script takes a `--model` flag and a `--provider` flag (ollama, anthropic, openai) so it's model-agnostic
- Supports `--batch-size` for rate limiting and `--resume` for interrupted runs (tracks progress in a `tagging_progress` table)

**`scripts/review_tags.py`** — CLI review tool for human curation.

- Presents staged tags one by one (or filtered by tradition/text/concept)
- Shows: chunk content, proposed concept, score, justification
- Reviewer can: accept, reject, or re-assign to a different concept
- Accepted tags with score >= 2 become EXPRESSES edges in the live graph
- New concept proposals go to `staged_concepts` (see architecture doc Section 4.6.4)

### Pass C: Cross-Tradition Edge Proposals

**`scripts/propose_edges.py`**

- Requires Stage 4 (vector indexing) to be partially complete — needs embeddings to find similar chunk pairs
- For each chunk, finds top-5 most similar chunks from *other traditions*
- Sends each cross-tradition pair to an LLM for classification (parallel / contrast / surface_only / unrelated)
- Writes proposed edges to staging:

```sql
CREATE TABLE staged_edges (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_concept  TEXT NOT NULL,
    target_concept  TEXT NOT NULL,
    edge_type       TEXT NOT NULL,       -- PARALLELS | CONTRASTS | DERIVES_FROM
    confidence      REAL,
    justification   TEXT,
    source_chunk    TEXT,                -- chunk that motivated this proposal
    target_chunk    TEXT,
    status          TEXT DEFAULT 'pending',
    tier            TEXT DEFAULT 'proposed',  -- proposed | verified (after review)
    reviewed_by     TEXT,
    reviewed_at     TIMESTAMP
);
```

**`scripts/review_edges.py`** — CLI review tool for edge proposals.

- Presents proposed edges with both source chunks side by side
- Reviewer can: accept (promote to live graph), reject, or reclassify
- Accepted edges get tier = 'verified'; unreviewed accepted edges stay 'proposed'

### Acceptance Criteria

- [ ] `guru.db` contains all tradition nodes, concept nodes, and chunk nodes
- [ ] Every chunk has at least one BELONGS_TO edge
- [ ] LLM tagging produces staged_tags entries for every chunk
- [ ] After human review, the densest cluster (Gnosticism–Hermeticism–Neoplatonism–Kabbalah) has EXPRESSES edges covering at least 80% of chunks
- [ ] At least 20 cross-tradition PARALLELS or CONTRASTS edges exist in the live graph after review
- [ ] All edges carry a justification string

### Tasks

```
3.1  Write concepts/taxonomy.toml (starter concept vocabulary)
3.2  Write guru.db schema (nodes, edges, staged_tags, staged_edges, staged_concepts)
3.3  Build graph_bootstrap.py (create DB, insert tradition/concept/chunk nodes, BELONGS_TO edges)
3.4  Build tag_concepts.py (LLM-assisted tagging with structured scoring prompt)
     3.4.1  Implement provider abstraction (ollama, anthropic, openai)
     3.4.2  Implement progress tracking and --resume
     3.4.3  Implement --batch-size rate limiting
     3.4.4  Write structured scoring prompt template
3.5  Build review_tags.py (CLI review tool for staged tags)
     3.5.1  Filter modes: by tradition, by text, by concept, by score
     3.5.2  Accept/reject/reassign workflow
     3.5.3  New concept promotion flow (staged_concepts → concept node)
3.6  Build propose_edges.py (cross-tradition pair classification)
     3.6.1  Integration with vector store (Stage 4 dependency)
     3.6.2  LLM pair classification prompt
     3.6.3  Deduplication (don't re-propose already-reviewed pairs)
3.7  Build review_edges.py (CLI review tool for staged edges)
3.8  QA pass: spot-check 10 EXPRESSES edges and 10 PARALLELS edges for correctness
```

---

## Stage 4: Vector Indexing

### Goal

Embed all chunks and load them into a vector store for semantic retrieval. This stage runs in parallel with Stage 3 (the graph needs embeddings for Pass C, and the vector store needs the graph for hybrid retrieval).

### Embedding Pipeline

**`scripts/embed_corpus.py`**

- Reads all chunks from `corpus/`
- Embeds each chunk's `content.body` using the configured embedding model
- Stores embeddings in the vector database with full metadata for filtering

Configuration:

```toml
# config/embedding.toml

[model]
provider = "ollama"            # ollama | sentence_transformers | api
model_name = "nomic-embed-text"
dimensions = 768

[vector_store]
backend = "chromadb"           # chromadb | qdrant
persist_directory = "./data/vectordb"
collection_name = "guru_chunks"

[processing]
batch_size = 64
show_progress = true
```

### Metadata Stored Per Vector

Every vector carries enough metadata to support filtered retrieval:

```python
{
    "id": "gnosticism.gospel-of-thomas.013",
    "tradition": "gnosticism",
    "text_id": "gospel-of-thomas",
    "text_name": "Gospel of Thomas",
    "section": "Logion 77",
    "translator": "Thomas O. Lambdin",
    "token_count": 62,
    "concepts": ["divine_immanence", "light_metaphor", "unity"],  # populated after Stage 3 review
}
```

The `concepts` field is backfilled after Stage 3 tagging is reviewed. This enables filtered vector search: "find chunks about `emanation_hierarchy` that are semantically similar to this query" — combining concept-tag filtering with vector similarity.

### Scripts to Build

**`scripts/embed_corpus.py`** — Embedding pipeline.

- Reads chunks from `corpus/`
- Optionally reads accepted concept tags from `guru.db` to populate metadata
- Embeds and upserts into vector store
- Supports `--resume` (tracks which chunks are already indexed)
- Supports `--reindex` (force re-embed all chunks, e.g., after model change)

**`scripts/backfill_concepts.py`** — Updates vector metadata after Stage 3 review.

- Reads accepted EXPRESSES edges from `guru.db`
- Updates the `concepts` metadata field on corresponding vectors
- Idempotent — safe to run repeatedly as new tags are reviewed

### Acceptance Criteria

- [ ] Every chunk in `corpus/` has a corresponding vector in the store
- [ ] Vector count matches chunk count exactly
- [ ] Metadata fields are complete and correctly typed
- [ ] Similarity search returns plausible results (manual spot-check: query "divine light within all things" should return Gospel of Thomas logion 77, Corpus Hermeticum passages, Upanishad passages)
- [ ] Filtered search works: querying with `tradition != "gnosticism"` excludes Gnostic chunks
- [ ] Concept backfill correctly populates the `concepts` metadata field

### Tasks

```
4.1  Write config/embedding.toml
4.2  Build embed_corpus.py
     4.2.1  Embedding model abstraction (ollama, sentence_transformers, API)
     4.2.2  Vector store abstraction (ChromaDB, Qdrant)
     4.2.3  Progress tracking and --resume
     4.2.4  Metadata construction from chunk TOML + guru.db
4.3  Build backfill_concepts.py (sync concept tags from guru.db to vector metadata)
4.4  Validation script: verify vector count == chunk count, spot-check similarities
4.5  Benchmark: measure embedding throughput and retrieval latency
```

---

## Stage 5: Retrieval & Model Integration

### Goal

Wire the vector store and concept graph into a hybrid retrieval pipeline, connect it to a language model, and enforce the mandated quotation procedure. The model is abstracted — the pipeline doesn't assume a specific LLM.

### Hybrid Retriever

**`guru/retriever.py`** — Core retrieval logic.

```python
class HybridRetriever:
    """
    Combines vector similarity search with concept graph traversal
    to find relevant chunks across traditions.
    """

    def __init__(self, vector_store, graph_db, config):
        self.vector_store = vector_store
        self.graph = graph_db
        self.config = config

    def retrieve(self, query: str, user_prefs: UserPreferences, top_k: int = 15) -> list[RetrievedChunk]:
        # Path 1: Vector similarity
        vector_results = self._vector_search(query, user_prefs, k=top_k * 2)

        # Path 2: Concept graph walk
        concepts = self._extract_concepts(query)
        graph_results = self._graph_walk(concepts, user_prefs)

        # Merge, deduplicate, re-rank
        merged = self._merge_and_rerank(vector_results, graph_results, user_prefs)
        return merged[:top_k]

    def _vector_search(self, query, prefs, k):
        """Embed query, search with tradition/text filters from user prefs."""
        filters = prefs.to_vector_filters()  # builds WHERE clause from whitelist/blacklist
        return self.vector_store.query(query, k=k, filters=filters)

    def _extract_concepts(self, query):
        """Identify concept nodes relevant to the query.
        Uses keyword matching against concept labels + optional LLM extraction."""
        ...

    def _graph_walk(self, concepts, prefs):
        """From matched concepts, walk PARALLELS/CONTRASTS edges,
        collect chunks via EXPRESSES edges, filter by user prefs."""
        ...

    def _merge_and_rerank(self, vector_results, graph_results, prefs):
        """Deduplicate, then score by:
        1. Tradition diversity (boost results spanning multiple traditions)
        2. Edge tier weight (verified 1.0x, proposed 0.7x, inferred 0.4x)
        3. Vector similarity score
        """
        ...
```

### User Preferences Integration

**`guru/preferences.py`**

```python
@dataclass
class UserPreferences:
    mode: str                           # "all" | "whitelist" | "blacklist"
    blacklisted_traditions: list[str]
    blacklisted_texts: list[str]
    whitelisted_traditions: list[str]
    whitelisted_texts: list[str]

    def is_chunk_allowed(self, chunk: RetrievedChunk) -> bool:
        """Returns True if this chunk passes the user's scope filter."""
        ...

    def to_vector_filters(self) -> dict:
        """Converts preferences to vector store query filters."""
        ...

    @classmethod
    def allow_all(cls) -> 'UserPreferences':
        """Default: everything enabled."""
        ...

    @classmethod
    def from_toml(cls, path: str) -> 'UserPreferences':
        """Load from user_preferences.toml."""
        ...
```

### Prompt Assembly

**`guru/prompt.py`**

Constructs the final prompt from retrieved chunks, user query, and system instructions.

```python
def build_prompt(query: str, chunks: list[RetrievedChunk], prefs: UserPreferences) -> str:
    """
    Assembles the full prompt:
    1. System instructions (citation rules, persona)
    2. Retrieved context (formatted chunks with full metadata)
    3. User query
    """

    context_block = format_chunks(chunks)
    # Each chunk formatted as:
    # ---
    # [Tradition | Text | Section]
    # Translator: {translator}
    # Concepts: {concepts}
    # Confidence: {tier}
    #
    # {body}
    # ---

    return SYSTEM_PROMPT.format(
        retrieved_chunks=context_block,
        active_traditions=prefs.active_tradition_summary(),
        query=query,
    )
```

System prompt template:

```
You are Guru, a scholar of comparative esoteric and religious traditions.

You answer questions by drawing on a curated corpus of primary texts.
You specialize in identifying conceptual overlaps and divergences
between traditions.

ACTIVE TRADITIONS: {active_traditions}

CITATION RULES:
- Every claim must include a citation: [Tradition | Text | Section]
- Direct quotes use quotation marks. Paraphrases do not.
- When drawing cross-tradition parallels, cite all relevant traditions.
- If a connection is based on a ◇ Proposed edge, use hedging language
  ("there appears to be a parallel...").
- If you cannot find a supporting source, say so. Never fabricate.
- Never cite texts outside the active traditions listed above.

RETRIEVED CONTEXT:
{retrieved_chunks}

USER QUERY:
{query}
```

### Model Abstraction

**`guru/model.py`** — LLM provider abstraction.

```python
class ModelProvider(Protocol):
    def complete(self, prompt: str) -> str: ...

class OllamaProvider:
    def __init__(self, model: str = "qwen3:8b", base_url: str = "http://localhost:11434"): ...
    def complete(self, prompt: str) -> str: ...

class AnthropicProvider:
    def __init__(self, model: str = "claude-sonnet-4-20250514"): ...
    def complete(self, prompt: str) -> str: ...

class OpenAIProvider:
    def __init__(self, model: str = "gpt-4o"): ...
    def complete(self, prompt: str) -> str: ...
```

Configuration:

```toml
# config/model.toml

[model]
provider = "ollama"            # ollama | anthropic | openai
model_name = "qwen3:8b"
temperature = 0.3              # low temp for factual grounding
max_tokens = 2048

[retrieval]
top_k = 15                     # chunks injected into prompt
vector_weight = 0.5            # weight for vector similarity in re-ranking
graph_weight = 0.5             # weight for graph-based results
diversity_boost = 1.3          # multiplier for cross-tradition results
```

### CLI Interface

**`guru/cli.py`** — Main entry point for interactive use.

```
$ guru query "How does the concept of divine spark appear across traditions?"

Searching... (15 chunks retrieved from 5 traditions)

The concept of a divine spark — a fragment of transcendent light or
consciousness embedded within the human being — appears across multiple
esoteric traditions with striking structural parallels.

[Gnosticism | Gospel of Thomas | Logion 77] "I am the light that is over
all things. I am all: from me all came forth, and to me all attained."

[Hermeticism | Corpus Hermeticum | Tractate I, Section 6] The Poimandres
describes the divine Light as the origin of the human nous, a luminous
fragment that descends into matter...

[Vedanta | Chandogya Upanishad | 6.8.7] The repeated refrain "tat tvam asi"
(thou art that) identifies the individual atman with the universal Brahman...

---
Citations: 6 | Traditions: 4 | Chunks used: 12/15 | Edge tiers: ◆ 8, ◇ 3, ○ 1
```

### Acceptance Criteria

- [ ] Hybrid retrieval returns results from multiple traditions for cross-tradition queries
- [ ] User preference filtering prevents excluded traditions from appearing in results or citations
- [ ] The agent never cites a text outside the user's active scope
- [ ] Every substantive paragraph in the agent's response contains at least one citation
- [ ] The agent uses hedging language for ◇ Proposed edges
- [ ] The agent explicitly states when it cannot find a source ("No source found in the current corpus for this claim")
- [ ] Swapping model providers (ollama → anthropic → openai) requires only a config change
- [ ] End-to-end latency for a query is under 10 seconds (excluding model inference time)

### Tasks

```
5.1  Build guru/retriever.py (HybridRetriever)
     5.1.1  Vector search path with preference filtering
     5.1.2  Concept extraction from query (keyword + optional LLM)
     5.1.3  Graph walk (concept → PARALLELS/CONTRASTS → EXPRESSES → chunks)
     5.1.4  Merge and re-rank with tradition diversity boost and tier weighting
5.2  Build guru/preferences.py (UserPreferences dataclass + filtering logic)
5.3  Build guru/prompt.py (chunk formatting + system prompt template)
5.4  Build guru/model.py (provider abstraction)
     5.4.1  OllamaProvider
     5.4.2  AnthropicProvider
     5.4.3  OpenAIProvider
5.5  Build guru/cli.py (interactive query interface)
5.6  Write config/model.toml
5.7  End-to-end integration test: query → retrieve → prompt → respond → verify citations
5.8  Citation accuracy test: verify 20 agent responses cite real chunks with correct metadata
5.9  Preference filtering test: verify excluded traditions never leak into responses
```

---

## Cross-Cutting Concerns

### Project Structure

```
guru/
├── config/
│   ├── embedding.toml
│   └── model.toml
├── concepts/
│   └── taxonomy.toml
├── sources/
│   └── manifest.toml
├── chunking/
│   ├── gnosticism/
│   │   ├── gospel-of-thomas.toml
│   │   └── ...
│   └── ...
├── raw/                          # Stage 1 output (git-ignored, large)
├── corpus/                       # Stage 2 output (git-tracked)
│   ├── traditions.toml
│   └── ...
├── data/
│   ├── guru.db                   # Stage 3 output (SQLite)
│   └── vectordb/                 # Stage 4 output (git-ignored)
├── scripts/
│   ├── acquire.py
│   ├── chunk.py
│   ├── graph_bootstrap.py
│   ├── tag_concepts.py
│   ├── review_tags.py
│   ├── propose_edges.py
│   ├── review_edges.py
│   ├── embed_corpus.py
│   ├── backfill_concepts.py
│   └── downloaders/
│       ├── sacred_texts.py
│       ├── gnosis_org.py
│       ├── sefaria.py
│       ├── access_to_insight.py
│       └── generic_html.py
├── guru/                         # Stage 5 runtime library
│   ├── retriever.py
│   ├── preferences.py
│   ├── prompt.py
│   ├── model.py
│   └── cli.py
├── tests/
│   ├── test_chunking.py
│   ├── test_retrieval.py
│   ├── test_citations.py
│   └── test_preferences.py
└── pyproject.toml
```

### Dependencies

```toml
# pyproject.toml [project.dependencies]

[project]
name = "guru"
requires-python = ">=3.11"

dependencies = [
    "tomli",                  # TOML parsing (stdlib in 3.11+ but tomli for write support)
    "tomli-w",                # TOML writing
    "beautifulsoup4",         # HTML scraping (Stage 1)
    "requests",               # HTTP downloads (Stage 1)
    "tiktoken",               # Token counting (Stage 2)
    "chromadb",               # Vector store (Stage 4)
    "sentence-transformers",  # Fallback embedding model
    "rich",                   # CLI formatting (review tools, progress bars)
]

[project.optional-dependencies]
anthropic = ["anthropic"]
openai = ["openai"]
qdrant = ["qdrant-client"]

[project.scripts]
guru = "guru.cli:main"
```

### Execution Order & Dependencies

```
Stage 1 (Acquire)
    │
    ▼
Stage 2 (Chunk)
    │
    ├──────────────────────┐
    ▼                      ▼
Stage 3 Pass A+B       Stage 4 (Embed)
(Bootstrap + Tag)          │
    │                      │
    │◄─────────────────────┤  (Pass C needs embeddings)
    ▼                      │
Stage 3 Pass C ───────────►│
(Edge Proposals)           │
    │                      │
    ▼                      ▼
Stage 4 Backfill ◄─── concepts from Stage 3
    │
    ▼
Stage 5 (Serve)
```

Stages 3 and 4 have a circular dependency: Pass C of Stage 3 needs vector embeddings from Stage 4, and Stage 4's concept metadata backfill needs reviewed tags from Stage 3. The execution order is: Stage 4 (initial embed without concepts) → Stage 3 Pass C → Stage 3 review → Stage 4 backfill.

---

## Full Task Index

```
STAGE 1: CORPUS ACQUISITION
  1.1  Create sources/manifest.toml
  1.2  Build generic_html.py downloader
  1.3  Build sacred_texts.py downloader
  1.4  Build gnosis_org.py downloader
  1.5  Build sefaria.py downloader
  1.6  Build access_to_insight.py downloader
  1.7  Build acquire.py orchestrator
  1.8  QA pass: verify 1 text per tradition

STAGE 2: CHUNKING
  2.1  Define chunking config schema
  2.2  Write chunking configs for all v1 texts
  2.3  Build regex-based splitter
  2.4  Build heading-based splitter
  2.5  Build paragraph-grouping splitter
  2.6  Build chunk.py orchestrator
  2.7  Build token counter
  2.8  Write corpus/traditions.toml
  2.9  QA pass: verify chunk boundaries
  2.10 Round-trip test

STAGE 3: CONCEPT GRAPH
  3.1  Write concepts/taxonomy.toml
  3.2  Write guru.db schema
  3.3  Build graph_bootstrap.py
  3.4  Build tag_concepts.py
       3.4.1  Provider abstraction
       3.4.2  Progress tracking + resume
       3.4.3  Rate limiting
       3.4.4  Scoring prompt template
  3.5  Build review_tags.py
       3.5.1  Filter modes
       3.5.2  Accept/reject/reassign
       3.5.3  New concept promotion
  3.6  Build propose_edges.py
       3.6.1  Vector store integration
       3.6.2  Pair classification prompt
       3.6.3  Deduplication
  3.7  Build review_edges.py
  3.8  QA pass: spot-check edges

STAGE 4: VECTOR INDEXING
  4.1  Write config/embedding.toml
  4.2  Build embed_corpus.py
       4.2.1  Embedding model abstraction
       4.2.2  Vector store abstraction
       4.2.3  Progress tracking + resume
       4.2.4  Metadata construction
  4.3  Build backfill_concepts.py
  4.4  Validation script
  4.5  Benchmark throughput and latency

STAGE 5: RETRIEVAL & MODEL INTEGRATION
  5.1  Build guru/retriever.py
       5.1.1  Vector search with filtering
       5.1.2  Concept extraction
       5.1.3  Graph walk
       5.1.4  Merge and re-rank
  5.2  Build guru/preferences.py
  5.3  Build guru/prompt.py
  5.4  Build guru/model.py
       5.4.1  OllamaProvider
       5.4.2  AnthropicProvider
       5.4.3  OpenAIProvider
  5.5  Build guru/cli.py
  5.6  Write config/model.toml
  5.7  End-to-end integration test
  5.8  Citation accuracy test
  5.9  Preference filtering test

TOTAL: 42 tasks (27 primary + 15 subtasks)
```
