# Tagger-v5 cross-tradition backfill

**Kind:** targeted run (off the main ingest spine)
**Parent:** todo:7b1d7388 · **This node:** todo:a08fe227 (candidate assembly)

## Why

v4 is a disciplined tagger but its backfill failed: the 12 genuinely
cross-tradition drift concepts drew **100%** of their training positives from
the new corpus (theosophy / western_esoteric / gnosticism), so the finetune
never saw them attached to an older tradition and cannot tag them there.
Evidence: `incarnation × Gita` scored 27B=3, base=0, v4=0
(`rellm docs/qwen-3-4b-guru-v4-findings.md`). This run manufactures the missing
older-tradition positives: 27B-adjudicated tags on older-tradition chunks,
queued through the review gate, become v5 training positives.

Scope is **12 concepts only** — trinity, stellar_determinism, divine_immanence,
initiation, divination, esoteric_lineage, exorcism, gender, spirit_conjuration,
incarnation, qliphoth, talisman_magic. The new-corpus-native psychism concepts
(psychic_attack, etheric_projection, aura, thought_form, occult_police, …) are
**excluded on purpose**: they have no ancient home to backfill onto.

## Node 1 — candidate assembly (`scripts/assemble_v5_candidates.py`)

Read-only over `guru.db` + `data/lexical-fts.db`; stages nothing. For each
concept, gather older-tradition candidate chunks two ways and union them:

- **embedding kNN** — definition embedded with `nomic-embed-text`, top-N over
  `chunk_embeddings`, `tradition $nin` the new corpus. nomic runs hot
  (rank-40 cosine ~0.69), so `--min-sim` guards thin concepts more than it
  trims the top-N; the 27B is the precision gate, this leg is recall.
- **lexical FTS** — per-concept signature terms OR-ed into an FTS5 `MATCH`
  over `chunks_fts`, top-N by bm25, same tradition exclusion.

A lexical hit whose only matched signature terms are **false-friend-prone**
(and which the embedding leg did not independently surface) is flagged
`false_friend_prone` — a heads-up for the 27B, not a rejection. Canonical case:
qliphoth's "shells" matching a Kalevala passage about feeding a horse.

```
python3 scripts/assemble_v5_candidates.py           # defaults below
# --embed-top-n 40  --min-sim 0.62  --fts-top-n 25  --out-dir data/backfill-v5
```

### Outputs (`data/backfill-v5/`, git-ignored like `guru.db`)

The chunk-id lists are derived from the local DB and vary across checkouts, so
they live beside the DB, not in git. This doc (script + counts) is the tracked,
reproducible record.

| file | role |
|---|---|
| `union-chunk-ids.txt` | deduped union — the `--chunk-ids-from-file` input for node 2 |
| `candidates.jsonl` | one `{concept, chunk, methods, embed_sim, bm25, matched_terms, false_friend_prone, snippet}` per line |
| `counts.md` | per-concept and per-concept×tradition counts |

### Snapshot (defaults, 2026-09-05)

531 union chunks · 710 (concept, chunk) pairs · 132 false-friend flags, across
19 older traditions (neoplatonism 176, christian_mysticism 100,
renaissance_hermeticism 57, hinduism 52, egyptian 28, … down to norse/sufism 1).

| concept | candidates | ff-flagged | concept | candidates | ff-flagged |
|---|---:|---:|---|---:|---:|
| trinity | 62 | 2 | exorcism | 53 | 13 |
| stellar_determinism | 63 | 17 | gender | 60 | 20 |
| divine_immanence | 64 | 1 | spirit_conjuration | 65 | 17 |
| initiation | 55 | 7 | incarnation | 64 | 13 |
| divination | 57 | 2 | qliphoth | 58 | 17 |
| esoteric_lineage | 64 | 23 | talisman_magic | 45 | 0 |

## Downstream

- **Node 2** (todo:577a88b7, GPU): `tag_concepts.py --chunk-ids-from-file
  data/backfill-v5/union-chunk-ids.txt`, 27B teacher, full 154 taxonomy,
  think-on. Writes `staged_tags(pending)`. No auto-promote.
- **Node 3** (todo:34a846d5): filter to the 12 target concepts on older
  traditions, reject the false-friends, queue accept/reject via
  `/guru-review-tags`. Owner keeps the apply gate.
- **Node 4** (todo:92e23071): after the owner applies, verify non-zero
  older-tradition rows for the 12 concepts, hand off to rellm v5 retrain.
