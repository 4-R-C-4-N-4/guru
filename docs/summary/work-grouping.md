# Work Grouping Table (V3 + V10 resolution)

Decided 2026-07-04. This table is the **dossier-unit census**: one row per
work, 53 works over 213 text dirs / 4,395 chunks / 2.72M tokens (totals
reconcile exactly against the live DB, except transcendental-magic's 219
chunks, which enter the DB with their deferred embed/tag pass —
todo:bd94d820). It resolves checklist items V3 and
V10 of `document-knowledge-data-structures.md`; the schema consequences are
in that doc's §6.1.

## Decisions

**V10 — grouped, option (a): a works layer, no re-manifest.** 170 of the 213
text dirs are serialization shards of 10 works. Shard→work membership is
declared in `sources/works.toml` (`[[work]] id / label / members` in reading
order); any text not listed is implicitly its own singleton work. text_ids,
chunk ids, tags, and edges are untouched — the works layer is pure mapping.
The dossier unit and the level-2 summary unit are the **work**; each shard
member is a natural section (structure entry + L1 span(s)) within it.

**V3 — the `-index` collections stay whole.** `plotinus-select-works-index`
(373.6k) and `egyptian-book-of-the-dead-index` (261k) each remain one text =
one singleton work with one dossier; the fold machinery (§1.3.5) absorbs
their size, and `structure_json` gives per-treatise/per-spell-group
navigation without any id churn. Same rationale as V10(a): splitting would
ripple through 4,176 chunk ids, 35k edges, and all accepted tags for a
navigation benefit the dossier already provides. Revisit only if study-mode
UX later needs sub-text scoping.

**Judgment calls worth recording:**

- `corpus-hermeticum-01…17` — the tractates are independent works
  bibliographically, but at 1–4k tokens each they are section-sized here;
  grouped as one collection work whose structure entries are the tractates
  (mirrors the kept-whole V3 collections, at smaller scale).
- `poetic-edda-hovamol` / `-voluspo` — NOT grouped. Each is a substantial
  (~12k), independently-studied poem: proper works, not serialization shards.
- `paracelsus-*` (4) — four distinct treatises; not grouped.
- `book-of-concealed-mystery` / `greater-` / `lesser-holy-assembly` — three
  distinct Zoharic texts from Mathers' *Kabbalah Unveiled*; not grouped.
  `kabbalah-unveiled-intro` is Mathers' own introduction: kept standalone,
  flagged secondary, dossier optional.
- `gathas-introduction` — translator/editor introduction, same policy:
  standalone, secondary, dossier optional. The `yasna-*` chapters group as
  the five Gathas.
- `plato-republic-6-*`/`-7-0` — excerpt shards of Republic Books VI–VII;
  grouped as one excerpt work. `plato-phaedo` etc. remain singletons.

**Effect on V5 (themes floor):** tag pooling under works collapses the
thin-tags tail from 79 texts (<10 accepted tags) to **3 works**:
`bundahishn` (0), `gathas-introduction` (2), `kojiki-beginning-heaven-earth`
(5). Themes floor: works with <5 accepted tags export `themes = []`.

## The 53 works (10 grouped, 43 singleton)

Bold `work_id` = grouped (n > 1). Token/chunk figures are sums over members.

| work_id | tradition | label | members | n | chunks | tokens | plan |
|---|---|---|---|---|---|---|---|
| **dhammapada** | buddhism | The Dhammapada | `dhammapada-chapter-01` … `dhammapada-chapter-26` (26) | 26 | 66 | 40,338 | ~7 spans |
| diamond-sutra | buddhism | Vajrakkhedika (Diamond Cutter) | — | 1 | 19 | 14,524 | ~3 spans |
| heart-sutra-smaller | buddhism | Prajña-pâramitâ-hridaya (Heart Sutra) | — | 1 | 1 | 664 | single span |
| mabinogion | celtic | The Mabinogion | — | 1 | 192 | 141,424 | ~24 spans + folds |
| **dionysius-divine-names** | christian_mysticism | On the Divine Names (Pseudo-Dionysius) | `dionysius-divine-names-1` … `dionysius-divine-names-13` (13) | 13 | 123 | 92,161 | ~16 spans |
| dionysius-mystical-theology | christian_mysticism | Pseudo-Dionysius: The Mystical Theology | — | 1 | 11 | 6,404 | single span |
| eckhart-sermons-field | christian_mysticism | Meister Eckhart's Sermons (Field translation) | — | 1 | 23 | 14,866 | ~3 spans |
| life-and-doctrines-boehme | christian_mysticism | The Life and Doctrines of Jacob Boehme | — | 1 | 159 | 118,421 | ~20 spans + folds |
| egyptian-book-of-the-dead-index | egyptian | The Egyptian Book of the Dead (Papyrus of Ani) | — | 1 | 357 | 261,095 | ~44 spans + folds; V3: kept whole; 1 fold layer |
| egyptian-heaven-and-hell | egyptian | The Egyptian Heaven and Hell | — | 1 | 96 | 62,795 | ~11 spans |
| kalevala | finnic | The Kalevala | — | 1 | 275 | 186,063 | ~32 spans + folds |
| gospel-of-philip | gnosticism | Gospel of Philip | — | 1 | 13 | 10,188 | ~2 spans |
| gospel-of-thomas | gnosticism | Gospel of Thomas | — | 1 | 114 | 6,476 | single span |
| pistis-sophia | gnosticism | Pistis Sophia | — | 1 | 160 | 121,333 | ~21 spans + folds |
| orphic-hymns | greek_mystery | Orphic Hymns | — | 1 | 138 | 62,963 | ~11 spans |
| pythagorean-golden-verses | greek_mystery | The Golden Verses of Pythagoras | — | 1 | 122 | 79,059 | ~14 spans |
| **corpus-hermeticum** | hermeticism | Corpus Hermeticum (Mead) | `corpus-hermeticum-01` … `corpus-hermeticum-17` (17) | 17 | 62 | 42,819 | ~8 spans |
| book-of-concealed-mystery | jewish_mysticism | The Book of Concealed Mystery (Siphra Dtzenioutha) | — | 1 | 9 | 6,581 | single span |
| enoch-charles-1917 | jewish_mysticism | The Book of Enoch (1 Enoch, Charles translation) | — | 1 | 141 | 61,810 | ~11 spans |
| greater-holy-assembly | jewish_mysticism | The Greater Holy Assembly (Idra Rabba Qadisha) | — | 1 | 3 | 1,835 | single span |
| kabbalah-unveiled-intro | jewish_mysticism | The Kabbalah Unveiled | — | 1 | 16 | 11,745 | ~2 spans; secondary (translator intro) — dossier optional |
| lesser-holy-assembly | jewish_mysticism | The Lesser Holy Assembly (Idra Zuta Qadisha) | — | 1 | 2 | 901 | single span |
| sefer-yetzirah | jewish_mysticism | Sefer Yetzirah (The Book of Formation) | — | 1 | 7 | 5,308 | single span |
| **gnostic-john-baptizer** | mandaean | The Gnostic John the Baptizer (Mandaean John-Book) | `gnostic-john-baptizer-1`, `gnostic-john-baptizer-2`, `gnostic-john-baptizer-3` | 3 | 66 | 36,833 | ~7 spans |
| adapa-food-of-life | mesopotamian | Adapa and the Food of Life | — | 1 | 2 | 1,297 | single span |
| descent-of-inanna | mesopotamian | The Descent of the Goddess Ishtar into the Lower World | — | 1 | 3 | 1,961 | single span |
| enuma-elish | mesopotamian | Enuma Elish: The Epic of Creation | — | 1 | 12 | 8,749 | ~2 spans |
| **gilgamesh** | mesopotamian | The Epic of Gilgamesh | `gilgamesh-tablet-01` … `gilgamesh-tablet-12` (12) | 12 | 39 | 26,541 | ~5 spans |
| iamblichus-on-the-mysteries | neoplatonism | Iamblichus: On the Mysteries | — | 1 | 218 | 114,141 | ~20 spans + folds |
| plotinus-select-works-index | neoplatonism | Select Works of Plotinus | — | 1 | 752 | 373,575 | ~63 spans + folds; V3: kept whole; 1 fold layer |
| poetic-edda-hovamol | norse | The Poetic Edda: Hovamol | — | 1 | 16 | 12,002 | ~3 spans |
| poetic-edda-voluspo | norse | The Poetic Edda: Voluspo | — | 1 | 16 | 12,258 | ~3 spans |
| plato-phaedo | platonism | Plato: Phaedo | — | 1 | 44 | 32,895 | ~6 spans |
| plato-phaedrus | platonism | Plato: Phaedrus | — | 1 | 38 | 28,661 | ~5 spans |
| **plato-republic** | platonism | Republic, Books VI-VII (Plato) | `plato-republic-6-0` … `plato-republic-7-0` (4) | 4 | 37 | 27,727 | ~5 spans |
| plato-symposium | platonism | Plato: Symposium | — | 1 | 36 | 27,207 | ~5 spans |
| plato-timaeus | platonism | Plato: Timaeus | — | 1 | 50 | 38,121 | ~7 spans |
| **agrippa-natural-magic** | renaissance_hermeticism | Occult Philosophy, Book I: Natural Magic (Agrippa) | `agrippa-natural-magic-ch-01` … `agrippa-natural-magic-ch-74` (74) | 74 | 126 | 73,569 | ~13 spans |
| **heroic-enthusiasts** | renaissance_hermeticism | The Heroic Enthusiasts (Gli Eroici Furori, Bruno) | `heroic-enthusiasts-pt1`, `heroic-enthusiasts-pt2` | 2 | 112 | 82,322 | ~14 spans |
| paracelsus-aurora-of-philosophers | renaissance_hermeticism | Paracelsus: The Aurora of the Philosophers | — | 1 | 22 | 17,086 | ~3 spans |
| paracelsus-coelum-philosophorum | renaissance_hermeticism | Paracelsus: Coelum Philosophorum, or Book of Vexations | — | 1 | 14 | 10,992 | ~2 spans |
| paracelsus-tincture-of-philosophers | renaissance_hermeticism | Paracelsus: The Book Concerning the Tincture of the Philosophers | — | 1 | 13 | 9,657 | ~2 spans |
| paracelsus-treasure-of-treasures | renaissance_hermeticism | Paracelsus: The Treasure of Treasures for Alchemists | — | 1 | 5 | 3,342 | single span |
| kojiki-beginning-heaven-earth | shinto | The Kojiki: The Beginning of Heaven and Earth | — | 1 | 1 | 230 | single span; 5 accepted tags — themes floor case |
| masnavi-book-1 | sufism | The Masnavi, Book I (Rumi) | — | 1 | 37 | 24,193 | ~5 spans |
| tao-te-ching-legge | taoism | Tao Te Ching | — | 1 | 81 | 12,946 | ~3 spans |
| zhuangzi-inner-chapters-index | taoism | The Writings of Chuang Tzu (Inner Chapters) | — | 1 | 57 | 42,007 | ~8 spans |
| isa-upanishad | upanishads | Îsâ-Upanishad | — | 1 | 2 | 869 | single span |
| tertium-organum | western_esoteric | Tertium Organum (P.D. Ouspensky) | — | 1 | 225 | 164,937 | ~28 spans + folds |
| **transcendental-magic** | western_esoteric | Transcendental Magic: Its Doctrine and Ritual (Éliphas Lévi) | `transcendental-magic-doctrine`, `transcendental-magic-ritual` | 2 | 219 | 154,536 | ~26 spans + folds; added 2026-07-14 (todo:bd94d820), not yet in DB — embed/tag deferred; summary campaign c2 |
| bundahishn | zoroastrianism | Bundahishn (Creation) | — | 1 | 2 | 1,132 | single span; 0 accepted tags — themes floor case |
| **gathas** | zoroastrianism | The Gathas of Zarathushtra (Yasna 28-34, 43-51, 53) | `yasna-28` … `yasna-53` (17) | 17 | 39 | 25,269 | ~5 spans |
| gathas-introduction | zoroastrianism | The Gathas: Translator's Introduction | — | 1 | 2 | 810 | single span; secondary (translator intro) — dossier optional |

## Notes for the span planner

- Grouped-work members are natural sections: each member ≥ its own L1 span;
  tiny members (Dhammapada chapters ~1.5k, Gathas ~1.5k) merge up to
  `span_target` as `§1.3.5` span packing already specifies, so member and
  span are not always 1:1. Merging does the real work corpus-wide: many
  texts label sections per-chunk (Plotinus has 752 distinct `section`
  values for 752 chunks), so unmerged natural sections would over-fragment
  into ~3,100 spans.
- "~N spans" is the `ceil(tokens/6k)` lower bound; natural-section
  boundaries will push the real count somewhat higher. `span_target` is
  reader-facing (TOC granularity) and provider-independent — it does not
  change when the generation backend does (design doc §1.3.6).
- "+ folds" marks the 8 works > 100k tokens where a fold layer is
  *possible* — but folds are **provider-conditional** (§1.3.6): under the
  default `claude-code` campaign the condition never fires and the plan
  emits zero fold rows. The flag matters only for `local` campaigns, and
  then with certainty only for Plotinus, Book of the Dead, and Kalevala.
- Works with a single span take the degenerate-case rule (one summary staged
  at level 2, no separate L1): 14 of 52 works at the ~6k `span_target`.
