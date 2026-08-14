# All-rejected staged_tags audit — apparatus vs. taxonomy-blind (todo:495577b7)

Source (b) of the rule-parity fix: the 316 chunks where every staged_tags
proposal was rejected (`GROUP BY chunk_id HAVING` every row `status='rejected'`
— zero accepted/pending/reassigned survivors). Each chunk's first ~700 chars
were read and classified against the tag-review rubric's apparatus criteria
(`prompts/ingest/tag-review.md` rule 1: translator/editor front matter,
footnote-numbered scholarly apparatus, TOC, publication boilerplate,
glossaries). Conservative default: uncertain → taxonomy-blind.

**74 apparatus** (queued via `scripts/flag_apparatus.py`, see below) ·
**242 taxonomy-blind** (real content the taxonomy doesn't happen to score —
recorded here so the read isn't lost, no action taken).

## Apparatus (74) — queued as pending staged_cleanups + reclassify review_actions

| cluster | count | why |
|---|---|---|
| `mandaean.gnostic-john-baptizer-{1,2,3}` | 26 | G.R.S. Mead's dense numbered scholarly footnotes — matches todo:6e0c2a63's "~25/66... Mead footnotes" estimate closely |
| `egyptian.egyptian-book-of-the-dead-index` | 20 | Budge's scholarly Introduction essay + bibliographic footnotes (dynasty dating, papyrus provenance, French Egyptological citations) — not the Papyrus of Ani translation itself |
| `finnic.kalevala` .272-.275 | 4 | back-matter mythological-name glossary (alphabetical entries, no narrative) |
| `buddhism.dhammapada-chapter-*` | 4 | bare translator citation fragments (e.g. `"Beal, Dhammapada, p. 76.]"`) |
| `western_esoteric.tertium-organum` | 7 | title page, table of contents, author's preface (x2), bibliographic footnote lists (x2), bare pagination list |
| `western_esoteric.secret-teachings-of-all-ages` .001-.003 | 3 | Manly P. Hall's author preface / acknowledgments / dedication signature — the book's actual body text (.004 onward) is NOT flagged (see taxonomy-blind below) |
| `neoplatonism.iamblichus-on-the-mysteries` .217-.218 | 2 | publisher's book catalogue (Bertram Dobell back-matter advertisement) — outside the roll-up's .162-.180 range |
| `egyptian.egyptian-heaven-and-hell.001` | 1 | Budge title page / publication credit |
| `jewish_mysticism.enoch-charles-1917.006` | 1 | R.H. Charles's scholarly Introduction (apocalyptic-literature dating discussion) |
| `norse.poetic-edda-{hovamol,voluspo}.001` | 2 | Bellows' editor's introductory notes |
| `zoroastrianism.bundahishn.001-002` | 2 | West's scholarly Introduction to Pahlavi Texts |
| `renaissance_hermeticism.heroic-enthusiasts-pt1.001-002` | 2 | translator's preface + errata; biographer's essay on Bruno's birthplace (also in source a) |

## Taxonomy-blind (242) — real content, no flag

The taxonomy simply doesn't score these well; they are not apparatus and
must never be excluded from tagging or the derived-parallels generator.
Largest clusters:

| cluster | count | what it actually is |
|---|---|---|
| `western_esoteric.secret-teachings-of-all-ages` (.004 onward) | 92 | Manly P. Hall's actual encyclopedic body text (Mysteries, Hermeticism, Freemasonry, Rosicrucianism, Atlantis, Kabbalah chapters) — the book's primary content, not apparatus |
| `native_american.mooney-cherokee-myths` | 43 | genuine Cherokee legend/history/place-name narrative (Mooney's ethnographic primary text) |
| `celtic.mabinogion` | 27 | genuine Mabinogion narrative prose (Peredur, Geraint, Pwyll, Branwen tales) — secular chivalric romance the mystical-concept taxonomy doesn't cover well |
| `neoplatonism.plotinus-select-works-index` | 16 | genuine Plotinus *Enneads* text (MacKenna translation) |
| `hinduism.yoga-sutras-book-*` | 22 | genuine Patanjali sutra + Charles Johnston commentary |
| `renaissance_hermeticism.agrippa-natural-magic-ch-*` | 14 | genuine Agrippa "Natural Magic" content (divination, omens, sympathetic virtues) |
| `greek_mystery.pythagorean-golden-verses` | 4 | Hierocles' commentary, incl. untranslated Greek verse quotations (Hesiod) — genuinely part of the primary text, just not in English |
| `hinduism.bhagavad-gita-chapter-*` | 3 | genuine Gita dialogue |
| everything else | 21 | single chunks across julian-revelations, gospel-of-thomas, gilgamesh tablets, eastman, plato dialogues, paracelsus, transcendental-magic-ritual, enoch — all genuine narrative/doctrinal content |

Full 316-chunk id lists (apparatus / taxonomy-blind) are reproducible via the
query in `scripts/flag_apparatus.py::all_rejected_chunk_ids()` plus the
hardcoded `SOURCE_B_APPARATUS` classification in that script — not
duplicated here to avoid a second copy going stale.

## Source (a) note — todo:6e0c2a63 roll-up

71 candidates had an exact chunk id or numeric range in the roll-up's prose.
Cross-checked against staged_tags acceptance history: 67 of 71 already carry
reviewer-**accepted** EXPRESSES tags (`dionysius-mystical-theology.001` alone
has 16, including `apophatic_theology` at score 3) — the roll-up's
one-line-per-range description names a contamination *pattern* somewhere in
the range, not "every chunk in this range is pure apparatus." Only 4 survive
a zero-surviving-tags filter: `heroic-enthusiasts-pt1.001-002`,
`orphic-hymns.001`, `kalevala.273`. See `scripts/flag_apparatus.py`'s
`SOURCE_A_CANDIDATES` for the full 71 and the runtime filter that keeps this
safe on re-run. Full accounting: todo:495577b7 analysis entry 0.

Several roll-up findings named no exact chunk id at all (`~25/66 mandaean...`,
`Budge... in egyptian works`, `Legge/Mueller... in zhuangzi + diamond-sutra`)
and are out of scope here — flagging a guessed chunk id would be a verdict
nobody earned by reading. A follow-up audit that names exact chunks is the
right way to pick these up.
