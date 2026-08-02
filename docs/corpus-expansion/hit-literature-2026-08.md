# Corpus Expansion — Hit-Literature Legs + Complements

*Compiled 2026-08-01. All URLs below verified live (HTTP 200 + title check) on
that date unless flagged otherwise. Builds on `docs/corpus-expansion-candidates.md`
(2026-05-28, partially executed in PR #28) — items still open from that doc are
marked **[carried]**; everything else is new. Honors the §0.2 editorial principle
(no outsider-voice sources on subaltern traditions) and the supported-host
preference: sacred-texts.com, gnosis.org, ccel.org, gutenberg.org.*

Current corpus for reference: 21 traditions, ~400 manifest sources. Weight sits in
upanishads (176), renaissance_hermeticism (80), christian_mysticism (29),
buddhism (28). Single-text traditions: sufism, shinto, celtic, finnic.

---

## 1. New legs — hit literature

Ranked by expected cohesion + name recognition.

### 1.1 Bhagavad Gita — new leg `hinduism` *(headline pick)*

The single biggest hit missing from the corpus. 176 Upanishad sources and no
Gita. Two clean PD routes, pick one:

- **Edwin Arnold, *The Song Celestial* (1885)** — `https://sacred-texts.com/hin/gita/index.htm`,
  `html_multi`, 18 chapter pages. The famous verse rendering (Gandhi's favorite).
- **K.T. Telang, SBE 8 (1882)** — `https://sacred-texts.com/hin/sbe08/index.htm`,
  `html_multi`. Scholarly prose, matches the Müller SBE house style already
  dominant in the corpus, and `_sbe_strip.py` already handles SBE footnote apparatus.

**Recommendation:** Telang/SBE8 for pipeline fit; Arnold if register matters more.
Cohesion: karma-yoga/jnana/bhakti triad, `detachment`, theophany (ch. 11 ↔ Ezekiel/
Revelation throne visions), "the Self is never born, never dies" ↔ Katha Upanishad
already held. Instantly the corpus's best-connected text.

Also under this leg:

- **Yoga Sutras of Patanjali** — Charles Johnston 1912,
  `https://sacred-texts.com/hin/yogasutr.htm`, `html`, regex-split on sutra numbers.
  Sources `meditation`/`samadhi` concepts from the practice side.
- **Songs of Kabir** — Rabindranath Tagore trans. 1915,
  `https://sacred-texts.com/hin/sok/index.htm`, `html_multi`, page-as-chunk per song.
  Insider-voice (Tagore translating within his own devotional culture). THE
  hinduism↔sufism bridge text — Kabir speaks both idioms natively; wires straight
  to Masnavi `separation_from_source` / `divine_intoxication`.

### 1.2 Stoicism — new leg `stoicism`

The candidates doc already leans on "`apocatastasis` (Stoic/Origenist recurrence)"
for its eschatology cluster — but the corpus holds **zero Stoic sources**. Both
picks are all-time hit literature:

- **Marcus Aurelius, *Meditations*** — George Long trans. 1862, Gutenberg #2680,
  `https://www.gutenberg.org/cache/epub/2680/pg2680-images.html`, `html`
  (generic_html, kalevala pattern), regex-split on BOOK headers + numbered entries.
- **Epictetus, *Enchiridion*** — T.W. Higginson trans., Gutenberg #45109,
  `https://www.gutenberg.org/cache/epub/45109/pg45109-images.html`, `html`,
  regex-split on numbered sections (52 short chapters — near page-as-chunk grain).

Cohesion: `logos`, cosmic sympathy (↔ Iamblichus), amor fati / providence,
premeditatio malorum ↔ Buddhist impermanence contemplation, the inner citadel ↔
`interior_castle`-family concepts. Marcus ↔ Plato (philosopher-king who actually
reigned) and ↔ Julian's hymns if §5.2 of the old doc lands.

### 1.3 Biblical selections (KJV) — new leg `biblical`

The corpus constantly gestures at Eden, the Flood, Job, and Revelation in its
notes and edges (Adapa "Eden/forbidden-food motif", Enuma Elish "and Genesis")
without holding a word of the Bible. KJV is both public domain (US) and the
single most influential piece of English hit literature. Targeted books, not the
whole canon — mirror the Republic-VI/VII precedent:

- Index: `https://sacred-texts.com/bib/kjv/index.htm`; per-book indexes verified:
  `job.htm`, `ecc.htm`, `joh.htm`, `rev.htm` (chapters at e.g. `ecc001.htm`).
- Suggested slice: **Genesis 1–11** (creation/Eden/Flood/Babel — direct
  Mesopotamian edges), **Job** (theodicy ↔ Boehme), **Ecclesiastes** (vanity ↔
  impermanence, pairs with Dhammapada/Hávamál gnomic register), **Song of Songs**
  (bridal mysticism — the source-text behind Zohar and Sufi Beloved imagery),
  **Gospel of John 1–17** (Logos prologue ↔ Corpus Hermeticum I is a canonical
  scholarly parallel; farewell discourse ↔ Gospels of Thomas/Philip), **Revelation**
  (↔ Bundahishn frashokereti, Ragnarök, Book of Enoch already held).
- `html_multi` per book index → page-as-chunk per chapter.

Cohesion argument is overwhelming: gnosticism, christian_mysticism, jewish_mysticism,
and mandaean legs all *presuppose* this text.

### 1.4 Chinese classics — new leg `confucianism` (or fold into a `chinese` umbrella)

- **I Ching** — James Legge, SBE 16, `https://sacred-texts.com/ich/index.htm`,
  `html_multi`, page-as-chunk per hexagram (64 natural units). Hit literature by
  any measure; `numerical_mysticism` ↔ Sefer Yetzirah's letter-combinatorics is a
  genuinely strong PARALLELS candidate (two divinatory-combinatoric cosmologies).
- **Confucian Analects** — Legge, `https://sacred-texts.com/cfu/conf1.htm`, `html`,
  regex-split on book/chapter numbering. CONTRASTS payoff: the great this-worldly
  counterpoint to the corpus's mystical bias — same aphoristic register as Tao Te
  Ching (same translator) but opposite metaphysical temperament. Pairs with
  Hávamál/Golden Verses in the practical-wisdom cluster.

### 1.5 Rubaiyat of Omar Khayyam — extends `sufism` (or `persian`)

FitzGerald 1859, Gutenberg #246,
`https://www.gutenberg.org/cache/epub/246/pg246-images.html` (contains 1st and
5th editions; pre-strip to one edition), `html`, quatrain-group chunks.
*(Note: NOT on sacred-texts — `isl/khayyam.htm` 404s.)* Arguably the most-quoted
poem in English; `divine_intoxication` + memento mori. Caveat: FitzGerald reads
Khayyam as an Epicurean skeptic, not a Sufi — tag accordingly (that tension is
itself a good CONTRASTS edge vs. Rumi).

### 1.6 William James, *The Varieties of Religious Experience* — extends `western_esoteric`

Gutenberg #621, `https://www.gutenberg.org/cache/epub/621/pg621-images.html`,
`html`, regex-split on Lecture headers. 1902, clean PD. The natural companion to
Tertium Organum (Ouspensky quotes James at length) and the corpus's only
*second-order* text — a study OF mysticism. If dossier/edge layers ever want a
"commentary" node type, this is the prototype; until then it slots as
western_esoteric consciousness-studies alongside Hall and Ouspensky.

### 1.7 Sikhism — new leg `sikhism` *(optional)*

M.A. Macauliffe, *The Sikh Religion* (1909), `https://sacred-texts.com/skh/index.htm`
(verified; Japji + Guru Nanak's hymns inside vol. 1). Macauliffe worked under Sikh
scholars (Kahn Singh Nabha) and the translation was vetted by Sikh authorities of
the day — arguably passes the §0.2 insider-centering test, but it IS a colonial-era
Englishman's frame around a living tradition's scripture. **Decide explicitly
against the editorial principle before ticketing.** Cohesion: Nanak is the
16th-century synthesis of exactly the Kabir-style Sant/Sufi confluence in §1.1.

### 1.8 Jainism — new leg `jainism` **[carried]**

Jacobi's *Jaina Sutras* (SBE 22/45), `https://sacred-texts.com/jai/index.htm`
(re-verified 2026-08-01). As per old doc §5.3: genuinely new epistemology
(anekantavada), `ascetic_discipline`. Lower edge density — second-tier priority.

---

## 2. Complements to existing legs

### buddhism
- **Lotus Sutra** — Kern, SBE 21, `https://sacred-texts.com/bud/lotus/index.htm`,
  `html_multi`. The most-read Buddhist scripture on earth (East Asian canon).
  Upaya/skillful-means + the burning-house parable ↔ Plato's Cave in the
  illusion/awakening cluster; universal buddhahood ↔ `theosis_deification`.
- **Awakening of Faith (Ashvaghosha)** — T. Suzuki 1900,
  `https://sacred-texts.com/bud/aof/index.htm`, `html_multi`. Tathagatagarbha/
  One-Mind treatise — the closest Buddhist analogue to emanationist metaphysics;
  strong Plotinus/Dionysius PARALLELS candidate.
- **Buddhist Suttas SBE 11** (first sermon, Maha-parinibbana) **[carried §4.11]** — still open, still verified.
- **Platform Sutra via Goddard** **[carried §4.6]** — `bud/bb/index.htm` re-verified.

### taoism
- **Zhuangzi Outer/Misc chapters** — SBE 40, `https://sacred-texts.com/tao/sbe40/index.htm`,
  `html_multi`. The existing manifest entry for the Inner Chapters literally says
  the rest "can be added separately" — this is that.
- **T'ai-Shang Kan-Ying P'ien** — Suzuki/Carus 1906,
  `https://sacred-texts.com/tao/ts/index.htm`, `html_multi`. Popular-religious
  Taoism (moral ledger karma) — CONTRASTS with philosophical Tao Te Ching, PARALLELS
  with Dhammapada karma-ethics and Egyptian negative confession.

### jewish_mysticism
- **Zohar (Nurho de Manhar, 1900–14)** — `https://sacred-texts.com/jud/zdm/index.htm`,
  `html_multi`. Actual sequential Zohar (Bereshith/Genesis commentary) vs. the
  Mathers/Rosenroth *excerpts* now held; would triple the leg's primary text.
  Pairs naturally with the Genesis 1–11 pick in §1.3 (same verses, mystical vs.
  plain reading — a made-to-order cross-tradition edge).

### christian_mysticism
- **Julian of Norwich, *Revelations of Divine Love*** — Grace Warrack ed. 1901,
  Gutenberg #52958, `https://www.gutenberg.org/ebooks/52958` (use
  `https://www.gutenberg.org/cache/epub/52958/pg52958-images.html`), `html`,
  regex-split on chapter headers. First English book by a woman; "all shall be
  well" ↔ apocatastasis cluster; corpus currently has zero women's voices.
- **Thomas à Kempis, *The Imitation of Christ*** — Gutenberg #1653,
  `https://www.gutenberg.org/cache/epub/1653/pg1653-images.html`, `html`.
  Candidate for most-read Christian book after the Bible — pure hit literature;
  devotio moderna practical register CONTRASTS with speculative Boehme/Eckhart.
- **Cloud of Unknowing [carried §4.7]**, **Theologia Germanica [carried §4.8]** —
  both re-verified 2026-08-01 (`chr/cou/index.htm`, CCEL toc).

### norse / greek / neoplatonism — still-open old-doc items, re-verified
- **Prose Edda (Brodeur)** `neu/pre/index.htm` **[carried §5.1]** — plus the other
  32 Poetic Edda poems beyond Völuspá/Hávamál (Grímnismál for cosmology,
  Baldrs draumar for the dead-raising seeress).
- **Hesiod Theogony + Works and Days** (`cla/hesiod/theogony.htm`, `works.htm`),
  **Homeric Hymns** (`cla/homer/hymns.htm`), **Sallustius** (`cla/fsgr/fsgr10.htm`)
  **[carried §5.2]** — all re-verified.
- **Eleusinian & Bacchic Mysteries (Thomas Taylor)** — *new*:
  `https://sacred-texts.com/cla/ebm/index.htm`, `html_multi`. Same translator-voice
  as the Orphic Hymns/Plotinus already held; the missing Eleusis node in greek_mystery.
- **Porphyry #77014 [carried §4.9]** — Gutenberg cache verified.

### sufism
- **Masnavi Books II–VI [carried §4.1]** — `isl/masnavi/index.htm` re-verified;
  still the best value-per-effort in the whole document.
- **Secret Rose Garden [carried §4.3]** — `isl/srg/index.htm` re-verified.
- **Bustan of Sa'di** — *new*: `https://sacred-texts.com/isl/bus/index.htm`,
  `html_multi`. Sa'di's ethical-mystical verse; middle register between Rumi's
  ecstasy and the Analects' pragmatism.

### shinto
- **Full Kojiki (Chamberlain)** — `https://sacred-texts.com/shi/kj/index.htm`,
  `html_multi`. Corpus holds only the opening section (1 chunk). The
  Izanagi-descends-to-Yomi episode is a direct Orpheus/Ishtar-descent parallel —
  one of the cleanest cross-tradition edges available anywhere, currently missing
  because the acquisition stopped one chapter short of it.

### western_esoteric
- **Swedenborg, *Heaven and Hell*** — `https://sacred-texts.com/swd/hh/index.htm`,
  `html_multi`, numbered sections (ideal chunking). The missing link between
  Boehme (already held) and 19th-c. esotericism (already held); correspondences
  doctrine ↔ `as_above_so_below`.

---

## 3. Blocked / flagged (wanted, but no clean route today)

- **Bardo Thodol (Tibetan Book of the Dead)** — old doc §5.3 cited
  `sacred-texts.com/tib/tbd/index.htm`; that URL **404s as of 2026-08-01** and the
  text no longer appears in sacred-texts' Tibetan index. Evans-Wentz 1927 is
  US-PD (not UK — he died 1965, so Global Grey doesn't carry it). Only live copy
  found: archive.org scan `the-tibetan-book-of-the-dead_202401` (1927 ed.) —
  scan/OCR, not pipeline-ready HTML. **Options:** (a) add an archive.org
  txt-extraction downloader (same decision as Dark Night of the Soul, old doc §6 —
  two texts now wait on it), or (b) keep deferring. The Egyptian↔Tibetan
  funerary-navigation edge remains the prize.
- **Popol Vuh** — no PD full English translation exists (Goetz–Morley is 1950,
  in copyright). sacred-texts' PD copy (`nam/pvuheng.htm`, verified) is Lewis
  Spence's 1908 *retelling* — an outsider summary of a Maya sacred text, which
  fails the §0.2 editorial principle on top of not being primary text. **Skip.**
- **Rubaiyat on sacred-texts** — `isl/khayyam.htm` 404s; use Gutenberg #246 (§1.5).
- **Dark Night of the Soul** — unchanged from old doc §6: PD Lewis translation is
  archive.org-only; CCEL's Peers is NOT PD. Waits on the same archive.org decision
  as the Bardo Thodol.

---

## 4. Suggested sequencing

1. **Bhagavad Gita + Yoga Sutras + Kabir** (§1.1) — biggest hit, biggest edge
   density, zero pipeline work.
2. **Stoicism pair** (§1.2) — cheap (two Gutenberg files), closes the
   apocatastasis cluster the old doc already designed around.
3. **KJV slice** (§1.3) — largest single cohesion payoff; needs a one-time
   decision on book list.
4. **Old-doc carries** — Masnavi II–VI, SBE11 suttas, Cloud of Unknowing,
   Prose Edda, Hesiod set (all re-verified, all still the right calls).
5. **East Asia round-out** — I Ching, Analects, Lotus Sutra, SBE40, full Kojiki.
6. **Second wave** — Zohar (Manhar), Julian of Norwich, Imitation, Swedenborg,
   James, Eleusinian Mysteries, Bustan, T'ai-Shang, Awakening of Faith.
7. **Decisions needed:** archive.org downloader (unblocks Bardo Thodol + Dark
   Night); Sikhism §0.2 call; `hinduism` vs. widening `upanishads` slug for the
   Gita leg.
