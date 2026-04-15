# Project Guru — Architecture Document

## Codename: Guru
## Scope: Corpus Ingestion, Concept Graph, and RAG-Powered Cross-Tradition Analysis

---

## 1. Problem Statement

Religious and esoteric traditions develop parallel concepts under radically different vocabularies. A scholar studying emanationism must independently connect Gnostic pleroma, Kabbalistic ein sof, Neoplatonic "the One," and Vedantic Brahman — but these connections live in different libraries, different languages, and different academic silos.

Guru is a domain-specific agent that ingests primary esoteric and religious texts, builds a concept graph capturing cross-tradition overlaps, and uses RAG to answer questions with traceable references back to source texts.

---

## 2. Design Principles

- **Local-first corpus.** All texts are gathered, chunked, and indexed locally. No dependency on external APIs for text retrieval at query time.
- **Graph similarity over vector-only retrieval.** Pure vector similarity misses structural parallels (e.g., "hierarchy of emanation" patterns) that graph relationships capture. Hybrid retrieval combines both.
- **Mandated quotation procedure.** Every claim the agent makes must carry a structured reference: `[Tradition | Text | Section/Verse]`. No permalinks in v1 — the citation format itself is the contract.
- **User-configurable scope.** Users control which traditions and texts are active in their session. The full corpus is always available; the user's active filter determines what the retrieval pipeline can see. No tradition is privileged by default.
- **Extensible corpus.** Adding a new tradition or text is a data operation (add chunks + tag concepts + embed), not a code change. The system treats the starter corpus as a seed, not a ceiling.
- **Honest scoping.** v1 covers a curated starter corpus, not "all world religion." The system is designed to grow, but launches tight.

---

## 3. Starter Corpus

### 3.1 Corpus Selection Criteria

Texts are selected for concept density, cross-tradition relevance, and public domain availability. Priority traditions for v1:

| Tradition | Texts | Source |
|-----------|-------|--------|
| Gnosticism | Nag Hammadi Library (Gospel of Thomas, Gospel of Philip, Apocryphon of John, Trimorphic Protennoia, On the Origin of the World) | gnosis.org, sacred-texts.com |
| Kabbalah | Sefer Yetzirah, selections from Zohar, Bahir | sefaria.org, sacred-texts.com |
| Hermeticism | Corpus Hermeticum, Emerald Tablet, Asclepius | sacred-texts.com |
| Neoplatonism | Plotinus Enneads (select tractates), Proclus Elements of Theology | sacred-texts.com, public domain translations |
| Vedanta | Principal Upanishads (Mandukya, Chandogya, Brihadaranyaka), Brahma Sutras | sacred-texts.com |
| Buddhism | Heart Sutra, Diamond Sutra, select Pali Canon (Dhammapada, Sutta Nipata) | accesstoinsight.org, sacred-texts.com |
| Christian Mysticism | Meister Eckhart sermons, Cloud of Unknowing, Pseudo-Dionysius (Divine Names, Mystical Theology) | sacred-texts.com, CCEL |
| Sufism | Ibn Arabi (Fusus al-Hikam excerpts), Rumi (Masnavi selections), Al-Hallaj | sacred-texts.com |
| Taoism | Tao Te Ching, Chuang Tzu (inner chapters) | sacred-texts.com |

### 3.2 Corpus Storage Format

Each text is stored as a collection of chunks in a local directory structure:

```
corpus/
├── traditions.toml          # tradition metadata registry
├── gnosticism/
│   ├── gospel-of-thomas/
│   │   ├── metadata.toml    # text-level metadata
│   │   └── chunks/
│   │       ├── 001.toml     # logion 1-5
│   │       ├── 002.toml     # logion 6-10
│   │       └── ...
│   ├── apocryphon-of-john/
│   └── ...
├── kabbalah/
└── ...
```

### 3.3 Chunk Schema

Each chunk carries enough metadata to generate a full citation without external lookup:

```toml
[chunk]
id = "gnosticism.gospel-of-thomas.013"
tradition = "Gnosticism"
text_name = "Gospel of Thomas"
section = "Logion 77"
translator = "Thomas O. Lambdin"
source_url = "http://gnosis.org/naghamm/gthlamb.html"  # archival, not runtime dependency

[content]
body = """
Jesus said, "I am the light that is over all things.
I am all: from me all came forth, and to me all attained.
Split a piece of wood; I am there.
Lift up the stone, and you will find me there."
"""

[annotations]
concepts = ["divine_immanence", "pantheism", "light_metaphor", "unity"]
related_chunks = ["hermeticism.corpus-hermeticum.005", "vedanta.chandogya.006"]
```

---

## 4. Corpus Extensibility & User Preferences

### 4.1 Adding New Traditions or Texts

Adding a new tradition (e.g., Jainism, Shinto, Indigenous Australian Dreamtime) or a new text within an existing tradition is a pure data pipeline operation with no code changes required:

1. **Add chunks.** Create a new directory under `corpus/`, write chunk TOML files following the schema in 3.3.
2. **Register the tradition.** Add an entry to `traditions.toml`:

```toml
[jainism]
id = "jainism"
label = "Jainism"
description = "Ancient Indian tradition emphasizing non-violence, non-absolutism, and asceticism."
enabled_by_default = true
tags = ["indian", "soteriology", "ascetic"]
texts = [
    { id = "tattvartha-sutra", label = "Tattvartha Sutra", sections_format = "chapter:verse" },
    { id = "uttaradhyayana", label = "Uttaradhyayana Sutra", sections_format = "lecture.verse" },
]
```

3. **Tag concepts.** Run the concept-tagging pipeline on the new chunks. The tagger proposes concept tags from the existing taxonomy and suggests new concepts where nothing fits.
4. **Review edges.** A human review pass accepts/rejects proposed `EXPRESSES` edges and creates any new `PARALLELS`/`CONTRASTS`/`DERIVES_FROM` edges connecting new concepts to existing ones.
5. **Embed and index.** Run the embedding pipeline on new chunks and upsert into the vector store.

The key invariant: after step 5, the new tradition is fully queryable. No prompt changes, no retrieval code changes, no retraining. The concept graph and vector store are the only integration surfaces.

### 4.2 Text-Level Metadata for Filtering

Each text entry in `traditions.toml` carries metadata that powers both UI filtering and retrieval scoping:

```toml
[gnosticism.texts.gospel-of-thomas]
id = "gospel-of-thomas"
label = "Gospel of Thomas"
tradition = "gnosticism"
era = "early_christian"             # rough period for timeline filtering
language_original = "Coptic"
sections_format = "logion"          # how to display section references
chunk_count = 22                    # auto-populated by ingestion
content_warnings = []               # optional, for sensitive material
tags = ["sayings_gospel", "nag_hammadi", "jesus_traditions"]
```

### 4.3 User Preference Model

Users configure which traditions and texts are active in their session. Preferences are stored per-user and applied as a filter at retrieval time — they do not alter the underlying corpus or graph.

```toml
# Example: user_preferences.toml (per-user, stored locally or in session state)

[scope]
# "all" = everything enabled, "whitelist" = only listed, "blacklist" = everything except listed
mode = "blacklist"

[scope.blacklist]
traditions = []                          # no entire traditions excluded
texts = ["sufism.al-hallaj"]             # user excludes a specific text

[scope.whitelist]
# only used when mode = "whitelist"
traditions = ["gnosticism", "kabbalah", "hermeticism", "neoplatonism"]
texts = []

[display]
show_tradition_tags = true
show_era_labels = true
citation_style = "inline"                # "inline" | "footnote" | "endnote"

[sensitivity]
# user can flag traditions they want included but treated with extra care
flag_traditions = []
```

### 4.4 How Preferences Flow Through the Pipeline

User preferences are not just a UI concern — they must be enforced at every stage of retrieval to prevent excluded texts from leaking into responses.

```
User Query + User Preferences
    │
    ├──► Vector Search
    │        └──► Filter: WHERE tradition NOT IN blacklist
    │                     AND text_id NOT IN blacklist
    │
    ├──► Graph Walk
    │        └──► Prune: Skip chunk nodes belonging to excluded texts/traditions
    │             (concept nodes remain — they're tradition-agnostic)
    │
    └──► Merge & Re-rank
             └──► Final filter: assert zero excluded chunks in context window
                  └──► Inject into prompt
```

Critical design decision: **concept nodes are never filtered out.** If a user disables Kabbalah but asks about emanation hierarchies, the concept `emanation_hierarchy` is still reachable — the agent just won't cite Kabbalistic texts to explain it. It will draw on whichever active traditions express that concept. This preserves the cross-tradition pattern-finding while respecting the user's scope.

If filtering removes so many chunks that the agent can't adequately answer a question, the agent should say so: "Your current scope excludes traditions that are primary sources for this topic. Consider enabling [Kabbalah, Neoplatonism] for a more complete answer."

### 4.5 UI Surface (Sketch)

The preference UI is a settings panel, not a query-time popup. Users configure it once and adjust as needed.

```
┌─────────────────────────────────────────────┐
│  📚 Corpus Scope                            │
│                                             │
│  Mode: ○ All traditions  ● Customize        │
│                                             │
│  ┌─────────────────────────────────────────┐ │
│  │ ☑ Gnosticism                        ▼  │ │
│  │   ☑ Gospel of Thomas                   │ │
│  │   ☑ Gospel of Philip                   │ │
│  │   ☑ Apocryphon of John                 │ │
│  │   ☐ Trimorphic Protennoia              │ │
│  │   ☑ On the Origin of the World         │ │
│  │                                         │ │
│  │ ☑ Kabbalah                          ▼  │ │
│  │   ☑ Sefer Yetzirah                     │ │
│  │   ☑ Zohar (selections)                 │ │
│  │   ☑ Bahir                              │ │
│  │                                         │ │
│  │ ☑ Hermeticism                       ▼  │ │
│  │ ☐ Neoplatonism                      ▼  │ │
│  │ ☑ Vedanta                           ▼  │ │
│  │ ☑ Buddhism                          ▼  │ │
│  │ ☑ Christian Mysticism               ▼  │ │
│  │ ☑ Sufism                            ▼  │ │
│  │ ☑ Taoism                            ▼  │ │
│  └─────────────────────────────────────────┘ │
│                                             │
│  Active: 34/38 texts across 8/9 traditions  │
│  [Reset to All]              [Save]         │
└─────────────────────────────────────────────┘
```

Collapsible tradition groups with per-text checkboxes. The top-level tradition checkbox toggles all texts within it. A counter at the bottom shows the active scope at a glance.

### 4.6 Assisted Curation Pipeline

Full automation of concept tagging and cross-tradition edge creation isn't realistic — word embeddings can't reliably distinguish between surface lexical similarity ("light" appears in many traditions) and deep structural parallels (emanation-by-overflow vs. emanation-by-contraction). But the human curation process can be dramatically accelerated with LLM assistance and community contribution.

#### 4.6.1 LLM-Assisted Tagging

Rather than asking an LLM open-ended questions about chunk content, the tagger uses a structured scoring prompt:

```
Given this text chunk and the concept taxonomy below, score each concept
0-3 for relevance to this passage:

  0 = unrelated
  1 = tangentially related
  2 = clearly relevant
  3 = this passage is a primary expression of this concept

Chunk: [chunk content]
Tradition: [tradition]
Text: [text name]

Concepts:
- divine_immanence
- emanation_hierarchy
- apophatic_theology
- ...

For each score >= 2, provide a one-sentence justification.
If the passage expresses a concept NOT in the taxonomy, propose it
with a definition and justification.

Respond in JSON.
```

Output goes to a staging table, not directly into the live graph. This turns human curation from "read every chunk and generate tags from scratch" into "review and correct LLM proposals" — roughly 5x faster.

#### 4.6.2 Cross-Tradition Edge Proposals

For PARALLELS and CONTRASTS edges, the system runs targeted comparison passes:

1. Vector search identifies chunk pairs across traditions with high embedding similarity.
2. An LLM classifies each pair into one of: `parallel` (same concept, different vocabulary), `contrast` (same domain, divergent claims), `surface_only` (lexical similarity without conceptual overlap), or `unrelated`.
3. The LLM provides a one-sentence justification for the classification.
4. Pairs classified as `parallel` or `contrast` generate proposed edges in the staging table.

Example output:

```json
{
  "chunk_a": "gnosticism.apocryphon-of-john.003",
  "chunk_b": "kabbalah.zohar.017",
  "classification": "parallel",
  "confidence": 0.85,
  "justification": "Both describe a hierarchical series of divine emanations from an unknowable source, though the Apocryphon uses aeon terminology while the Zohar uses sefirot."
}
```

#### 4.6.3 Confidence Tiers

Every edge in the concept graph carries a confidence tier:

| Tier | Label | Source | Agent Behavior |
|------|-------|--------|----------------|
| ◆ Verified | Human-reviewed | Manual curation or community review (see 4.7) | Cited as firm connection |
| ◇ Proposed | LLM-suggested | Automated tagging/comparison pipeline | Cited with hedging ("there appears to be a parallel...") |
| ○ Inferred | Algorithmic | Vector similarity above threshold, no LLM or human review | Used for retrieval ranking but not cited directly unless no better source exists |

Tier flows upward only: an edge starts as ○ Inferred or ◇ Proposed and can be promoted to ◆ Verified through review. Demotion (Verified → Proposed) requires an explicit dispute.

The retrieval re-ranker weights edges by tier: ◆ edges contribute full weight, ◇ edges contribute 0.7x, ○ edges contribute 0.4x. This means verified connections naturally surface first in cross-tradition queries.

#### 4.6.4 Concept Staging & Promotion

When the LLM tagger proposes a new concept not in the existing taxonomy, it enters a `staged_concepts` table:

```sql
CREATE TABLE staged_concepts (
    id              TEXT PRIMARY KEY,
    proposed_label  TEXT NOT NULL,
    definition      TEXT NOT NULL,
    justification   TEXT NOT NULL,
    proposed_by     TEXT NOT NULL,       -- "system" | user_id
    proposed_at     TIMESTAMP NOT NULL,
    status          TEXT DEFAULT 'pending',  -- "pending" | "accepted" | "rejected" | "merged"
    merged_into     TEXT,                -- if merged into existing concept
    review_notes    TEXT
);
```

A periodic review process (human or community-driven) evaluates staged concepts:

- **Accept:** promote to a full concept node in the graph.
- **Reject:** discard (with reason logged).
- **Merge:** the proposed concept is a duplicate or subset of an existing one — redirect all edges to the existing concept.

This mirrors the "capability namespace entries are permanent registry commitments" principle from P2P-CD: concepts in the live graph are stable identifiers, not ephemeral tags.

### 4.7 Hosted Platform & Token Economy

While the core Guru engine is designed local-first, the curation and community layer is a natural candidate for a hosted platform. A cloud-hosted instance enables user accounts, collaborative graph curation, and a token economy that incentivizes contribution.

#### 4.7.1 Platform Architecture

```
┌──────────────────────────────────────────────────────┐
│                    guru.domain.tld                    │
│                                                      │
│  ┌──────────┐  ┌──────────┐  ┌────────────────────┐  │
│  │  Web UI   │  │ Auth/    │  │  Curation API      │  │
│  │ (query +  │  │ Accounts │  │  (label, review,   │  │
│  │ settings) │  │          │  │   propose, dispute) │  │
│  └─────┬─────┘  └────┬─────┘  └─────────┬──────────┘  │
│        │              │                  │             │
│  ┌─────▼──────────────▼──────────────────▼──────────┐  │
│  │              Guru Engine (API layer)              │  │
│  │  ┌──────────┐ ┌───────────┐ ┌──────────────────┐ │  │
│  │  │ RAG      │ │ Concept   │ │ Token Ledger     │ │  │
│  │  │ Pipeline │ │ Graph     │ │ (user balances,  │ │  │
│  │  │          │ │ (SQLite/  │ │  earn/spend log)  │ │  │
│  │  │          │ │  Postgres)│ │                   │ │  │
│  │  └──────────┘ └───────────┘ └──────────────────┘ │  │
│  └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────┘
```

For a hosted deployment, SQLite would likely migrate to Postgres for concurrent multi-user access. The concept graph schema (Section 5.4) is already relational and ports directly.

#### 4.7.2 User Roles

| Role | Can Do | Earns Tokens |
|------|--------|--------------|
| Reader | Query the agent, configure tradition preferences | — |
| Labeler | Review proposed edges, vote on concept promotions | Yes |
| Contributor | Submit new chunks, propose new concepts, create edges | Yes |
| Curator | Accept/reject staged concepts, resolve disputes, merge duplicates | Yes (higher rate) |
| Admin | Manage users, configure system, override decisions | — |

New accounts start as Reader. Labeler unlocks after account verification. Contributor and Curator are earned through sustained quality contributions.

#### 4.7.3 Token Economy

Tokens are an internal currency that rewards curation work and gates premium features. They are *not* cryptocurrency — just an internal points system with clear earn/spend rules.

**Earning tokens:**

| Action | Tokens | Condition |
|--------|--------|-----------|
| Review a proposed edge (agree/disagree/flag) | 2 | Review must include a one-sentence justification |
| Propose a new cross-tradition edge | 5 | Edge must be accepted by a Curator |
| Submit a new text chunk with metadata | 3 | Chunk must pass QA and be accepted |
| Propose a new concept | 10 | Concept must be promoted from staging |
| Resolve a concept merge/dispute | 8 | Resolution must be accepted by another Curator |
| Consistent labeling streak (7 days) | 15 | Bonus for sustained contribution |

**Spending tokens:**

| Feature | Cost | Notes |
|---------|------|-------|
| Extended query depth (more chunks per query) | 1/query | Default retrieval is free; token-gated tier retrieves deeper |
| Export citations as structured bibliography | 5 | BibTeX / formatted reference list |
| Priority concept proposals (faster review queue) | 10 | Bumps your proposal to front of review queue |
| Request specific text addition to corpus | 20 | Flags a text for the ingestion pipeline |
| Access to raw concept graph data (API/export) | 15 | For researchers building on Guru's graph |

**Quality controls:**

- **Agreement scoring:** If a Labeler's reviews consistently disagree with Curator decisions (>40% disagreement rate over 50+ reviews), their token earn rate is halved and their reviews are flagged for secondary review. This discourages low-effort spam labeling.
- **Justification requirement:** Every label action requires a one-sentence justification. Actions without justifications earn zero tokens. This builds a corpus of human reasoning about *why* connections exist.
- **Cooldown on self-promotion:** Contributors cannot review their own proposed edges or concepts. Cross-review is mandatory.

#### 4.7.4 Labeling Interface (Sketch)

The core labeling task is simple: the system presents a pair of chunks and asks the user to classify the relationship.

```
┌─────────────────────────────────────────────────────────┐
│  🏷️ Edge Review                         +5 tokens      │
│                                                         │
│  ┌────────────────────┐  ┌────────────────────────────┐ │
│  │ GNOSTICISM         │  │ KABBALAH                   │ │
│  │ Apocryphon of John │  │ Zohar 1:15a                │ │
│  │ Section 4          │  │                            │ │
│  │                    │  │                            │ │
│  │ "And the Monad is  │  │ "Before the Holy One       │ │
│  │ a monarchy with    │  │ created any shape in the   │ │
│  │ nothing ruling     │  │ world, He was alone,       │ │
│  │ over it. It is the │  │ without form, resembling   │ │
│  │ God and Father of  │  │ nothing. Who can           │ │
│  │ everything..."     │  │ comprehend Him as He       │ │
│  │                    │  │ was before creation?"      │ │
│  └────────────────────┘  └────────────────────────────┘ │
│                                                         │
│  System suggests: PARALLEL (confidence: 0.85)           │
│  Concept: apophatic_theology                            │
│                                                         │
│  Your classification:                                   │
│  ◉ Parallel  ○ Contrast  ○ Surface only  ○ Unrelated   │
│                                                         │
│  Justification (required):                              │
│  ┌─────────────────────────────────────────────────────┐ │
│  │ Both describe an unknowable divine source beyond    │ │
│  │ form or comparison, using apophatic framing.        │ │
│  └─────────────────────────────────────────────────────┘ │
│                                                         │
│  [Skip]                                      [Submit]   │
└─────────────────────────────────────────────────────────┘
```

The system pre-populates its own classification and confidence score. Users can agree (fast path — just add justification and submit) or override. This makes labeling a 15-30 second task per pair, which is critical for sustained engagement.

---

## 5. Concept Graph

### 5.1 Purpose

The concept graph is Guru's core differentiator. Rather than relying purely on embedding similarity (which struggles when different traditions use entirely different vocabularies for the same idea), the graph explicitly models cross-tradition conceptual relationships.

### 5.2 Graph Structure

**Nodes** fall into three types:

- **Concept nodes** — abstract ideas that span traditions. Examples: `divine_immanence`, `emanation_hierarchy`, `ego_death`, `divine_feminine`, `apophatic_theology`, `cyclical_cosmology`.
- **Chunk nodes** — individual text chunks from the corpus, each linked to one or more concept nodes.
- **Tradition nodes** — top-level grouping (Gnosticism, Kabbalah, etc.) for filtering and traversal.

**Edges:**

| Edge Type | From → To | Meaning |
|-----------|-----------|---------|
| `EXPRESSES` | Chunk → Concept | This chunk discusses this concept |
| `PARALLELS` | Concept → Concept | These concepts are structurally or thematically analogous |
| `CONTRASTS` | Concept → Concept | These concepts address the same domain but diverge |
| `DERIVES_FROM` | Concept → Concept | Historical influence or textual dependency |
| `BELONGS_TO` | Chunk → Tradition | Provenance |

### 5.3 Concept Taxonomy (Starter)

The initial concept vocabulary is hand-curated, not auto-generated. This ensures the graph starts with meaningful nodes rather than noisy clusters. Concepts are organized by domain:

**Cosmology/Ontology:** `emanation_hierarchy`, `demiurge`, `pleroma_fullness`, `divine_spark`, `cyclical_cosmology`, `creation_ex_nihilo`, `maya_illusion`, `dependent_origination`

**Soteriology:** `gnosis_direct_knowledge`, `ego_death`, `theosis_deification`, `liberation_moksha`, `bodhisattva_path`, `via_negativa`, `divine_union`

**Theology/Metaphysics:** `apophatic_theology`, `divine_immanence`, `divine_transcendence`, `divine_feminine`, `logos_word`, `light_metaphor`, `unity_of_being`

**Praxis:** `meditation_contemplation`, `ascetic_practice`, `ritual_theurgy`, `sacred_sound_mantra`, `dream_vision`

### 5.4 Graph Storage

v1 uses a local graph stored as an adjacency list in SQLite (keeping the stack simple and file-portable). Schema:

```sql
CREATE TABLE nodes (
    id          TEXT PRIMARY KEY,   -- e.g. "concept:divine_immanence" or "chunk:gnosticism.gospel-of-thomas.013"
    node_type   TEXT NOT NULL,      -- "concept" | "chunk" | "tradition"
    label       TEXT NOT NULL,      -- human-readable name
    metadata    TEXT                -- JSON blob for extra attributes
);

CREATE TABLE edges (
    source      TEXT NOT NULL REFERENCES nodes(id),
    target      TEXT NOT NULL REFERENCES nodes(id),
    edge_type   TEXT NOT NULL,      -- "EXPRESSES" | "PARALLELS" | "CONTRASTS" | "DERIVES_FROM" | "BELONGS_TO"
    weight      REAL DEFAULT 1.0,   -- strength/confidence of relationship
    annotation  TEXT,               -- brief justification for the edge
    UNIQUE(source, target, edge_type)
);

CREATE INDEX idx_edges_source ON edges(source);
CREATE INDEX idx_edges_target ON edges(target);
CREATE INDEX idx_edges_type ON edges(edge_type);
```

---

## 6. RAG Pipeline

### 6.1 Indexing Pipeline

```
corpus/ (TOML chunks)
    │
    ├──► Embedding Model (e.g., nomic-embed-text or instructor-xl)
    │        └──► Vector DB (Qdrant local / ChromaDB)
    │                 chunk_id → embedding + metadata
    │
    └──► Concept Tagger (LLM-assisted)
             └──► Concept Graph (SQLite)
                      chunk ──EXPRESSES──► concept
```

**Chunking strategy:** Chunks respect document structure. A logion is a chunk. A sutra verse is a chunk. An Ennead tractate section is a chunk. Never split mid-thought. Target chunk size: 200–800 tokens, with the natural document unit as the primary boundary.

**Concept tagging:** Semi-automated. An LLM pass proposes concept tags for each chunk from the starter taxonomy + suggests new concepts. A human review pass accepts/rejects/merges. This keeps the graph honest.

### 6.2 Retrieval Pipeline

```
User Query
    │
    ├──► Embed query ──► Vector search (top-k chunks by similarity)
    │
    ├──► Extract concepts from query (LLM or keyword match)
    │        └──► Graph traversal:
    │               1. Find matching concept nodes
    │               2. Walk PARALLELS/CONTRASTS edges to related concepts
    │               3. Collect chunks linked via EXPRESSES edges
    │
    └──► Merge & re-rank results from both paths
              │
              └──► Inject top-N chunks into prompt + query ──► LLM ──► Response
```

The hybrid approach means a query like "what traditions describe a hierarchy of divine beings emanating from a source?" will find:

- **Vector path:** chunks containing words like "emanation," "hierarchy," "divine beings"
- **Graph path:** the `emanation_hierarchy` concept node → PARALLELS → `sefirot`, `aeons`, `hypostases` → EXPRESSES → chunks from Kabbalah, Gnosticism, Neoplatonism that may use completely different vocabulary

### 6.3 Re-ranking

After merging vector and graph results, re-rank by:

1. **Tradition diversity** — boost results that span multiple traditions (this is the whole point)
2. **Concept centrality** — chunks expressing concepts with many PARALLELS edges are more connective
3. **Vector similarity** — standard semantic relevance
4. **Recency of tradition** — no bias; weight equally

---

## 7. Agent Workflow

### 7.1 Mandated Quotation Procedure

Every factual claim the agent makes about a text must include a structured citation. The agent's system prompt enforces this format:

```
[Tradition | Text | Section] "Relevant excerpt or close paraphrase"
```

Examples:

```
[Gnosticism | Gospel of Thomas | Logion 77] "I am the light that is over all things."

[Kabbalah | Sefer Yetzirah | 1:1] The text describes thirty-two paths of wisdom
through which the divine established creation.

[Neoplatonism | Enneads | V.2.1] Plotinus argues that the One necessarily
overflows into emanation, not by choice but by the nature of absolute fullness.
```

Rules:
- Direct quotes use quotation marks. Paraphrases do not.
- Every paragraph of substantive analysis must carry at least one citation.
- When drawing a cross-tradition parallel, cite both sides.
- If the agent cannot find a source chunk to support a claim, it must say so explicitly rather than fabricating a reference.

### 7.2 System Prompt Skeleton

```
You are Guru, a scholar of comparative esoteric and religious traditions.

You answer questions by drawing on a curated corpus of primary texts.
You specialize in identifying conceptual overlaps and divergences
between traditions.

CITATION RULES:
- Every claim must include a citation: [Tradition | Text | Section]
- Direct quotes use quotation marks
- Paraphrases do not use quotation marks
- When drawing cross-tradition parallels, cite all relevant traditions
- If you cannot find a supporting source, say so. Never fabricate.

RETRIEVED CONTEXT:
{retrieved_chunks}

USER QUERY:
{query}
```

### 7.3 Query Flow (End-to-End)

1. User asks: "How does the concept of divine spark appear across traditions?"
2. **Concept extraction:** LLM identifies `divine_spark` as the key concept.
3. **Graph walk:** `divine_spark` → PARALLELS → `atman`, `pneuma`, `divine_light` → EXPRESSES → chunks from Upanishads, Gnostic texts, Hermetic texts, Sufi texts.
4. **Vector search:** parallel path retrieves chunks mentioning "spark," "inner light," "seed of God," etc.
5. **Merge + re-rank:** deduplicate, prioritize tradition diversity.
6. **Inject top 10-15 chunks** into prompt with full metadata.
7. **LLM generates response** with mandated citations.

---

## 8. Tech Stack (v1)

| Component | Choice | Rationale |
|-----------|--------|-----------|
| Corpus format | TOML files in directory tree | Human-readable, git-friendly, easy to curate |
| Concept graph | SQLite | Single-file, zero-config, portable |
| Vector store | ChromaDB (local) or Qdrant (local mode) | Runs locally, no cloud dependency |
| Embedding model | `nomic-embed-text` via Ollama | Local, decent quality, runs on consumer hardware |
| LLM (agent) | Qwen-3 8B via llama.cpp / Ollama | Matches existing local inference setup |
| LLM (concept tagging) | Same, or Claude API for batch tagging pass | Higher quality tagging justifies API cost |
| Orchestration | Python (LangChain or custom) | Flexibility for hybrid retrieval logic |

---

## 9. Build Phases

### Phase 1: Corpus Gathering & Chunking
- Collect public domain texts for the starter corpus
- Write ingestion scripts (scrape/download → normalize → chunk → TOML)
- Manual QA pass on chunk boundaries and metadata

### Phase 2: Concept Graph Bootstrap
- Define starter concept taxonomy (Section 5.3)
- LLM-assisted concept tagging of all chunks
- Human review and edge creation (PARALLELS, CONTRASTS, DERIVES_FROM)
- Load into SQLite graph

### Phase 3: RAG Pipeline + Preference Filtering
- Embed all chunks, load into vector store
- Implement hybrid retrieval (vector + graph walk)
- Build re-ranking logic with tradition diversity boost
- Implement user preference model (whitelist/blacklist filtering at vector and graph layers)
- Wire up to LLM with system prompt and citation enforcement

### Phase 4: Agent Polish
- Test citation accuracy and coverage
- Tune chunk retrieval count and re-ranking weights
- Add "I don't know" behavior for unsupported claims
- Test preference filtering (verify excluded traditions never leak into responses)
- Evaluate on a set of cross-tradition comparison questions

### Phase 5: Extensibility Validation
- Add one new tradition end-to-end (data only, no code changes) to prove the pipeline
- Build preference UI (settings panel with tradition/text toggles)
- Write contributor guide for adding new traditions (chunk format, tagging conventions, review process)

### Phase 6: Hosted Platform & Community Curation
- Deploy hosted instance with auth/accounts
- Build labeling interface for community edge review
- Implement token ledger (earn/spend tracking)
- Migrate SQLite → Postgres for concurrent multi-user access
- Implement agreement scoring and quality controls for labelers
- Launch with invite-only Labeler access, expand based on quality metrics

---

## 10. Open Questions

- **Concept granularity:** How fine-grained should concepts be? `emanation` vs. `emanation_hierarchy` vs. `sefirotic_emanation`. Too coarse loses signal; too fine fragments the graph.
- **Translation variance:** The same text in different translations can embed very differently. Do we index multiple translations per text, or pick a canonical one?
- **Graph maintenance:** Partially addressed by the assisted curation pipeline (Section 4.6) and community labeling (Section 4.7). Remaining question: what's the minimum viable Curator pool to keep review queues moving?
- **Agent skill packaging:** If Guru becomes a Hermes agent skill, the concept graph and vector store become plugin state. How does that interact with the existing session DB architecture? The hosted platform (Section 4.7) may make the agent skill model less relevant — or they could coexist as local and cloud tiers.
- **Token valuation:** How many tokens should premium features cost relative to earn rates? Too cheap and there's no incentive to contribute; too expensive and new users feel gated. Needs tuning with real usage data.
- **Preference presets:** Should there be named presets (e.g., "Western Esotericism" = Gnosticism + Hermeticism + Kabbalah + Neoplatonism; "Eastern Contemplative" = Buddhism + Vedanta + Taoism + Sufism) to reduce onboarding friction?
- **Copyright and licensing:** Most starter corpus texts are public domain, but some translations are not. Need a clear licensing policy per chunk, especially if community-contributed texts enter the corpus.
- **Labeler expertise:** Should labeling tasks be tradition-filtered so that users only review edges in traditions they've demonstrated knowledge of? Or does cross-tradition naivety sometimes surface unexpected connections?

---

## 11. Mandated Quotation Format — Quick Reference

| Element | Format |
|---------|--------|
| Tradition | Title case, standard name (e.g., "Gnosticism", not "Gnostic Christianity") |
| Text | Full title (e.g., "Gospel of Thomas", not "GThom") |
| Section | Native division: Logion, Verse, Chapter:Verse, Tractate.Section (e.g., "Logion 77", "V.2.1", "1:1") |
| Direct quote | Wrapped in quotation marks |
| Paraphrase | No quotation marks, but citation still required |
| Cross-tradition claim | Multiple citations, one per tradition referenced |
| Unsupported claim | Explicit disclaimer: "No source found in the current corpus for this claim." |
