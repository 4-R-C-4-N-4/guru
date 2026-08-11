# apocryphon-of-john — ingest decisions

The first text ingested from a PDF rather than a URL, and the first whose
source is a *synoptic* edition — one printed page carrying four manuscript
witnesses in parallel columns. Most of what is worth recording here follows
from those two facts.

---

## 01 — source-vetting · 2026-08-08 · claude

**Verdict:** verified

**URL:** <https://othergospels.com/john> — a landing page, not the artifact.
The artifact is a PDF downloaded from it.

**Licence:** public domain, by explicit dedication on page 1 of the PDF:
"committed to the public domain and may be freely copied and used, changed or
unchanged, for any purpose." Samuel Zinner's translation, edited by Mark M.
Mattison, published 2025-01-23.

The underlying Coptic edition (Waldstein & Wisse, Brill 1995) is still in
copyright. That does not travel: a translation made from a copyrighted critical
edition is the translator's own work to dedicate. Recorded because the
combination — a 2025 publication, in the public domain, made from an in-copyright
edition — reads as a contradiction if you only see two of the three facts.

**Notes for later nodes:** `format = "pdf"` has no downloader. `scripts/acquire.py`
will fail on this id, by construction rather than by defect. Node 02's artifact
is produced by `scripts/pdf_synoptic_extract.py` instead.

### The PDF is not retained, and that is a gap

The only record of where the artifact came from is the `url` in
`sources/manifest.toml`. The PDF itself is not in the repository and not on
the ingesting machine; `raw/gnosticism/apocryphon-of-john*.txt` are the
extractor's outputs and are git-ignored. If that landing page changes, the
extraction is not reproducible from anything we hold.

This is tolerable for a public-domain text with a stable-looking host and
intolerable as a general policy. Flagged rather than fixed — a raw-artifact
retention rule is a workbook-wide decision, not this text's to make.

---

## 02 — acquire · 2026-08-08 · claude

**Strategy:** positional, not heuristic.

The three columns have origins at 36.6 / 215.2 / 393.6 pt with clean gutters,
and parallel paragraph groups share a y-position across all three columns. Both
the per-witness reconstruction and a synoptic alignment therefore fall out of
the page geometry — no column-detection heuristic and no reading-order
guesswork.

Indent offset from the column origin carries the structure: prose continuation,
verse line, new paragraph, hanging continuation. Font runs carry the rest —
italics are Codex IV,1 readings, bold 11pt are Coptic page numbers, centred bold
12pt are the section headings shared across all three columns.

### Only Codex II,1 is manifested

The four witnesses are recensions of one treatise and run verbatim identical for
a paragraph at a stretch. Manifesting all of them would put near-duplicate
chunks into `chunk_embeddings` and have `propose_edges` draw PARALLELS between
the text and itself — a self-similarity artifact that would look like a genuine
cross-tradition finding and would be very hard to spot at node 14, because the
justifications would all be true.

Codex II,1 is the long recension, the only complete witness, and carries the
Codex IV,1 readings inline as italics, so one file covers two witnesses. BG 8502
and Codex III,1 are still extracted to `raw/` for reference and deliberately
left unmanifested.

### Page markers are carried as sentinels, not written as brackets

Markers are emitted qualified — `[II, 18]`, `[BG 19]`, `[III, 3]` — rather than
the print's bare `[18]`, because `clean_bodies.py`'s P9 rule (`\s*\[\d{1,3}\]`)
strips bracketed numbers as footnote references. Left bare, P9 ate them and left
an orphaned `[II,]` welded to the following sentence.

The non-obvious part: this **cannot** be fixed by rewriting brackets after
extraction. The printed text contains bracketed numbers of its own — "the other
[3]60 angels" is a restored digit inside a word — so there is no post-hoc rule
that distinguishes a page marker from a restoration. The marker has to be
carried as a sentinel from the moment the font run identifies it, and only
becomes a bracket once it has been qualified with its witness.

---

## 05 — chunk-config · 2026-08-08 · claude

**Strategy:** `regex-section-split` on `'==\s*([^=\n]+?)\s*=='`

The edition prints 19 editorial section headings shared across all three
columns — "Prologue", "The Savior Appears", … "Conclusion" — and the extractor
emits them as `== Heading ==`. They are the edition's own articulation of the
treatise and the units a reader would cite, so they are the boundaries here.
`section_label_format = "{n}"` passes the heading through as the label, so
sections are named rather than numbered.

**Rejected:**

| Strategy | Why not |
|---|---|
| `paragraph-group` | Would cut across the edition's own divisions, and the treatise's argument is organised by them. |
| Coptic page numbers (`[II, n]`) | They are codex pagination, not textual articulation — a page break lands mid-sentence. |
| `fixed-token` | Discards the only citation handles the edition offers. |

**Expected chunk count:** 19 sections · **Actual:** 24 chunks (11,803 tokens,
avg 491). Five sections exceeded `max_tokens = 800` and split — hence the
`Monad a` / `Monad b`, `Yaltabaoth a` / `Yaltabaoth b` labels.

**Pre-strip:** the tail "Translator's notes" block and the inline `[^n]`
references pointing into it. Scholarly apparatus per project policy (cf.
`gilgamesh-tablet-*.toml`, `pistis-sophia.toml`) — kept in the raw file,
dropped before chunking.

---

## 07–08 — clean-bodies, readability · 2026-08-08 · claude

**clean_bodies:** 0 changes. Expected — the extractor emits clean text by
construction, and the one rule that would have fired (P9) was designed around
at node 02.

**Readability:** worst chunk 40.0 against a corpus max of about 15. **Passed
anyway.**

The signal is `hard_wrap`, which counts short lines continued by a lowercase
line — which is exactly what verse colometry looks like. This translation is set
one clause per line:

> I am the Father,
> I am the Mother,
> I am the Son.

That structure is authorial and load-bearing; the Pronoia hymn in chunk 023 is
unreadable as reflowed prose. Preserved rather than flattened to satisfy the
auditor. Recorded here so the audit-table outlier is expected rather than
alarming — a future reader seeing 40.0 should not "fix" it.

---

## 09–13 · 2026-08-09 · claude

| node | result |
|---|---|
| 09 graph bootstrap | 24 chunk nodes |
| 10 tag proposals | 350 staged over 24/24 chunks, 0 errors |
| 12 embeddings | 24 rows, 0 errors |
| 13 edge proposals | 61 staged — 59 PARALLELS, 2 CONTRASTS, 0 errors |

Edge confidence quantised to {0.95: 20, 0.92: 1, 0.85: 40}, consistent with
Mistral's behaviour everywhere else in the corpus.

---

## 11 — tag review · 2026-08-10 · claude

**Judged:** 350 of 350 · **Queued:** 188 accept / 162 reject · **Applied by the
user in one cycle** (no reassigns, so the two-cycle problem documented in
node 11 did not arise).

Accept rate 54%, and it tracks the treatise's own structure closely:

| chunks | content | accept |
|---|---|---|
| 001–005 | frame narrative, the Monad | 23% |
| 006–013 | Barbelo, the four lights, Yaltabaoth, Adam's making | 62% |
| 014–015 | the body-part angel catalogue | 37% |
| 016–023 | animation, the archons' conspiracy, Eve, the soul's fate, the Pronoia hymn | 73% |
| 024 | colophon | 40% |

### The reviewable distinction is name versus content

Four concepts in this text appear both as a *proper name* and as a *doctrine*,
and the tagger cannot tell them apart. The rule that resolved them: does the
chunk say anything about the thing, or only use it as a label?

- **`aeons`** — declined on chunks 001–005 where "aeon" means a duration or a
  station; accepted from 006 on, where Barbelo, Idea, Precognition,
  Indestructibility, Eternal Life and Truth are enumerated as beings.
- **`divine_providence`** — declined five times where Providence is simply
  Barbelo's other name; accepted on 019, 022 and 023, where Providence acts —
  dispatching messengers, warning Noah, descending three times.
- **`divine_light`** — accepted where light is a quality or a medium of
  revelation; declined on 009, where "the first light, Armozel" is a proper
  name for a station.
- **`sacred_names`** — declined on the bare name catalogues (013, 014);
  accepted on 011, which claims *power dwelt in the names*.

### Wrong-referent tags are this model's most consistent error

`divine_hiddenness` was proposed nine times on the strength of *something*
being hidden — Yaltabaoth behind a cloud, the Reflection inside Adam, the
savior evading the archons — when the concept is the supreme God's concealment.
Six were rejected. The tell is that the justification names the hidden thing,
and it is not God.

### `hidden_sayings` splits cleanly by justification grammar

Every instance that opened "The text is titled 'Secret Writing'" was hollow;
every instance grounded in a passage — "not what Moses wrote", "spoken to those
who deserve it", "distribute them in secret" — was sound. This is a sharper
version of the title-only rule already in node 11's failure modes, and it held
without exception across 24 chunks.

### `numerical_mysticism` is genuine here, which is unusual

It is on node 11's over-application list, and it was accepted on five chunks:
pentad-equals-decad, the four lights times three aeons, the 365 angels, the
sevenfold week. That is a property of this treatise, not a calibration slip —
but it means the concept's noisiness is content-dependent, and a per-text prior
is worth more than a corpus-wide one.

---

## 14 — edge review · 2026-08-10 · claude

**Judged:** 61 of 61 · **Queued:** 34 PARALLELS accept, 1 CONTRASTS accept, 25
`surface_only`, 1 `unrelated` · applied by the user.

57% accept, against 35% on yoga-sutras. Zero of the 61 had a live edge, so the
whole pool was safe; the direct live-edge check from node 14 was used rather
than the skill's confidence proxy.

Accepts by partner tradition: western_esoteric 10, christian_mysticism 9,
jewish_mysticism 5, renaissance_hermeticism 4, mandaean 3, and one each from
sufism, neoplatonism, hermeticism, egyptian.

### The accept rate is a function of how checkable the chunk's claims are

Chunks 003–009 — the Monad, Barbelo, the aeons — produced 5 accepts in 20.
Everything apophatic resembles everything else apophatic, and "both describe an
ineffable source beyond category" is the surface trap in its purest form.
Chunks 010–024 produced 30 in 41, because those chunks make claims with edges
on them: *seven* powers, *not* the rib, *time* as the fetter.

The four strongest accepts are all of that kind:

- Boehme ↔ 018. Both explicitly reject Genesis's rib and substitute **power**:
  "not as Moses said, 'his rib'" against "the 'bones' and 'ribs' were
  nevertheless still power and strength."
- 022 ↔ 1 Enoch XV. Both answer the same question — where did the evil spirit
  come from? — with the same answer: angels who took the daughters of men.
- Boehme ↔ 013. Both deny direct creation by the supreme and distribute it
  across exactly **seven** powers.
- 023 ↔ Book of the Dead LXXX. "I have raised up those who wept and who had
  bidden their faces and had sunk down" against "he wept and the tears flowed …
  I also lifted him up."

### One partner chunk failed four times on an editor's headnote

`hermeticism.corpus-hermeticum-01.001` drew four proposals and lost all four.
Its body opens with a modern editor's bracketed headnote:

> `<This is the most famous of the Hermetic documents … The Fall has here
> become the descent of the Primal Man through the spheres of the planets to
> the world of Nature, a descent caused not by disobedience but by love, and
> done with the blessing of God.>`

Three justifications quoted doctrines that exist **only** in that headnote —
"the descent of the Primal Man", "caused not by disobedience but by love" —
including a 0.92 CONTRASTS. The Hermetic text in that chunk contains none of
it; the descent-by-love material is in chunk `.003`.

Node 14 already records "one Corpus Hermeticum chunk was matched on a modern
editor's bracketed headnote". It is this chunk, and it is not a one-off: it is
a chunk that advertises doctrines it does not contain, so it will keep
attracting proposals it cannot support. Tracked as a corpus-quality ticket.

The same doctrinal contrast, aimed at `.003` where the body genuinely says
"she smiled with love … they were lovers", is the one CONTRASTS that was
accepted (010 ↔ CH .003).

### The `*-index` apparatus tell is wrong in both directions

The `guru-review-*` skills list a `*-index.*` chunk id as an apparatus marker.
In this pass it misfired twice as a false positive:

- `neoplatonism.plotinus-select-works-index.702` is genuine Ennead text.
- `egyptian.egyptian-book-of-the-dead-index.213` is genuine Book of the Dead
  Chapter LXXX, and produced one of the best accepts in the pass.

And once as a true positive that needed a different fix:

- `egyptian.egyptian-book-of-the-dead-index.315` *is* Budge's introduction, and
  its body carries a raw footnote-number block — `2. Ibid., p. 132. 3. Ibid.,
  p. 140.` and so on for twelve entries. That is a chunker defect, not just
  apparatus.

The id is a naming artifact of how those texts were shelved, not a statement
about the chunk. Judge the body.

### Node 14 cannot repair a mis-aimed proposal — four measured instances

The proposer repeatedly found the right *partner text* and missed by one or two
chunks. Because node 14 has no `reassign`, each is a discarded true positive:

| proposal | outcome |
|---|---|
| Boehme `.096` ↔ 008 | surface — the spark doctrine is not in 008 |
| Boehme `.096` ↔ 016, ↔ 018 | both accepted — same insight, right chunks |
| Iamblichus `.038` ↔ 008 | surface — 008 is a static aeon list |
| Iamblichus `.038` ↔ 016 | accepted — 016 has the two-directional dynamics |
| Masnavi `.033` ↔ 009, ↔ 023 | surface ×2 — no reserve theme in either |
| Masnavi `.033` ↔ 024 | accepted — reserve is exactly what 024 is about |
| CH `.001` ↔ 006, 009, 017, 019 | surface ×4 — see headnote above |

In the Boehme, Iamblichus and Masnavi cases the *same* insight was recovered by
a correctly-aimed sibling proposal in the same pass, so nothing was lost. The
Corpus Hermeticum case is weaker: one of its four insights — the descent-into-
matter contrast — was recovered at `.003`, and the other three were not
proposed anywhere else. That will not always be true, and there is no mechanism
that makes it true; it happened because the proposer produced several
proposals per partner text.

This is the fourth independent confirmation of the gap node 14 already
documents. The loss stays unmeasured, because a discarded proposal leaves no
trace — the only evidence it existed is a table like this one, written by hand.

### Secret Teachings of All Ages is systematically a retelling

Eight of the 35 accepts have a `secret-teachings-of-all-ages` chunk on the other
side — second only to Boehme's `life-and-doctrines` at nine — and several of
those chunks are Hall retelling another tradition's text: Poimandres in `.073`
and `.076`, a doxography of Gnosticism in `.039`.

That is node 14's quotation-chunk pattern, but applying the quotation rule
mechanically would strip most of `western_esoteric` out of the Atlas, because
retelling is most of what the book *is*. The line taken: accept where the
doctrine is stated in the chunk as the author's own claim, decline where the
pairing rests on the retelling's frame rather than its content. `.039` — a
survey paragraph about what the Gnostics believed, paired with an actual
Gnostic text — was declined on exactly that ground: a description of a
tradition is not a parallel to it.

This needs a rule the workbook does not yet have.

### Confidence was mildly predictive here, against the yoga-sutras finding

| confidence | accepted | rejected | accept rate |
|---|---|---|---|
| 0.95 | 15 | 5 | 75% |
| 0.92 | 0 | 1 | 0% |
| 0.85 | 20 | 20 | 50% |

Node 14 records, from yoga-sutras, that "confidence predicts nothing well enough
to skip a reading — it decides order, not verdict." On this text the 0.95 tier
outperformed the 0.85 tier by 25 points. Recorded as a contradiction rather than
resolved: two texts is not a trend, the 0.95 tier here is only 20 edges, and the
operational rule is unchanged either way, because a 75% tier still contains five
wrong edges and there is no way to know which five without reading them.

What does hold across both texts is that confidence cannot be used as a *gate*.
The single 0.92 was the pass's worst proposal — a CONTRASTS resting entirely on
an editor's headnote — and it outranked forty 0.85s of which twenty were right.

---

## Post-pass state · 2026-08-10 · claude

Nodes 01–14 complete. Live graph state for this text: 24 chunk nodes, 188
`EXPRESSES` edges, 34 `PARALLELS`, 1 `CONTRASTS`. Both review queues drained by
the user; no pending `staged_tags` or `staged_edges` remain.

Not done, and deliberately out of scope here: `guru ingest status` reporting
`[x]` for nodes 10/12/13 on partial coverage (ticket `1f6d2c11`), and the
corpus-quality findings above, which are tickets against other texts rather
than against this one.
