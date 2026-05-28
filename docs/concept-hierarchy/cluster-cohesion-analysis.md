# Concept clustering — embedding-cohesion analysis

_2026-05-27 · evaluates the §4 hand-clustering (todo:ea1c2372) with data before
committing to further tweaks. Reproduce: `python scripts/cluster_cohesion.py`._

## Method

Each of the 95 concept **definitions** is embedded with the corpus model
(`config/embedding.toml` → `ollama/nomic-embed-text`, 768-d — the same space
retrieval uses). Per concept we compute a cosine-distance **silhouette** against
its assigned family:

    s_i = (b_i − a_i) / max(a_i, b_i)
    a_i = mean distance to other concepts in the same family   (cohesion)
    b_i = min over other families of mean distance to it       (separation)

`s_i < 0` ⇒ the concept is closer to some *other* family than its own.

## Headline finding — the embedder does not separate families

**Mean silhouette = −0.050**, and essentially every concept scores between −0.24
and +0.10. The underlying distances are all bunched: within-family ~0.30–0.45,
nearest-other-family ~0.27–0.40. The 95 esoteric-mystical definitions share so
much surface vocabulary ("divine", "soul", "cosmos", "spiritual") that
`nomic-embed-text` places them in one moderately-similar blob.

**A silhouette of −0.05 is noise, not a mis-fit** — the concept is 2–5% closer to
another family, within measurement slop. The §4 families encode *role/function*
distinctions ("what God **is**" vs "what God **does**"; "salvation through
knowing" vs "the realised state") that embedding similarity does not capture.

**Conclusion: do not re-cluster off these scores.** There is no cleaner
embedding-based grouping to move to; the hand-drawn §4 structure is about as good
as this embedder can distinguish. (Corollary for guru-web: *family-level*
retrieval expansion is inherently fuzzy in this space — families are a curated
overlay, not an embedding-derived structure.)

## Per-family mean silhouette (loosest → tightest)

```
-0.163 praxis.transformative_path (2)     -0.073 anthropology.human_constitution (4)
-0.151 ethics.moral_teaching (6)          -0.041 praxis.contemplative_practice (6)
-0.146 anthropology.spiritual_completion(4) -0.004 soteriology.purgation_and_emptiness(3)
-0.143 cosmology.origin_events (5)        +0.002 cosmology.cosmic_order (6)
-0.125 praxis.ecstatic_modes (2)          +0.007 soteriology.knowledge_path (6)
-0.120 theology.divine_nature (5)         +0.010 praxis.ritual_and_symbolic (6)
-0.096 soteriology.ecstatic_ascent (2)    +0.026 cosmology.soul_cosmology (3)
-0.092 cosmology.divine_structure (8)     +0.042 praxis.ascetic_discipline (3)
-0.090 theology.divine_attributes_and_acts(5) +0.045 soteriology.union_and_return (5)
-0.079 cosmology.cosmic_agents (5)        +0.059 theology.ontological_structure (4)
-0.075 soteriology.soteric_categories (2) +0.104 anthropology.divine_indwelling (3)
```

All low-magnitude — even the "tightest" families barely separate.

## Signals that survive the noise (large magnitude **and** semantically real)

1. **`ethics.moral_teaching` is the loosest real family** (−0.151; all 6 members
   negative, scattering to praxis/soteriology/anthropology). Corroborates §4's own
   note that ethics is small and provisional. *Leave; revisit if it grows past ~8.*
2. **`numerical_mysticism` → `cosmology.cosmic_order`** (s = −0.123). A genuine
   cross-cutting concept (numbers as cosmic structure vs as divine reality).
   Textbook **secondary-membership** (§5.3) candidate — a cross-link, not a move.
3. **`ecstatic_ascent` ↔ `ecstatic_modes` are indistinguishable** (`divine_madness`,
   `heroic_furor`, `divine_intoxication` cross between them). Two size-2 families
   the embedder can't tell apart; §4 itself raised merging them.
4. **`prophetic_rejection`** (−0.135) confirmed poorly held in `moral_teaching`.

## Verdict on the five previously-flagged placements

| concept | s | data verdict |
|---|---|---|
| `forbidden_knowledge` | **+0.098** | well-held — fits `knowledge_path`; earlier "foil" worry **not** borne out |
| `numerical_mysticism` | −0.123 | cross-cutting → cosmic_order (secondary-membership candidate) |
| `prophetic_rejection` | −0.135 | confirmed loose in moral_teaching |
| `emotional_epistemology` | −0.030 | ~equidistant (noise) — leaving it is fine |
| `nature_preservation` | −0.026 | ~equidistant (noise) — leaving it is fine |

## Decision (2026-05-27)

**Leave the clustering as-is.** No strong evidence to change it, and we're
mid-migration — let the dust settle before tweaking. The few real signals
(numerical_mysticism secondary membership, a possible ecstatic merge) are recorded
here and on the `ea1c2372` analysis note for a later, deliberate pass — not now.

Re-run `python scripts/cluster_cohesion.py` after any future clustering change to
re-evaluate. A sharper signal would need an instruction-tuned embedder or an LLM
pairwise "does X belong with Y" pass; marginal value is low given the families are
a deliberate human overlay this embedder can't adjudicate.
