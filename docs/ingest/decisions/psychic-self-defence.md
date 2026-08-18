# psychic-self-defence — ingest decisions

One file per text. Append as you go; do not rewrite history when a later node
contradicts an earlier one — record the contradiction and what it cost.

---

## 01 — source-vetting · 2026-08-17 · claude

**Verdict:** `insufficient-evidence` — held at node 01, not registered in
`sources/manifest.toml`, no `done` ledger entry.

**Candidate work:** Dion Fortune (Violet M. Firth), *Psychic Self-Defence: A
Study in Occult Pathology and Criminality*, first published 1930, London:
Rider & Co., copyright held by the Society of the Inner Light.

### The legal question is settled; the sourcing question is not

**US public-domain status of the 1930 work itself: high confidence PD as of
2026.** Fortune died 1946; UK copyright (life+70) ran to 2016, so the work
was still under copyright in its country of origin on the URAA's restoration
date (1996-01-01). That makes it a URAA-restored work rather than one that
was ever formally US-copyrighted and renewed. Restored foreign works
published 1923–1977 take the same **95-years-from-publication** term as
domestic works of that era (Sonny Bono Act, 17 U.S.C. §304) — not life+70 —
so 1930 + 96 = **2026**. Same mechanism, one publication-year later, as the
`secret-teachings-of-all-ages` entry's "US PD since 2024" note.

**What I could not do: point to a fetchable digitization confirmed to be the
1930 text.** Every copy located traces through a *later* printing:

| Item | Publisher / date | Rights signal | Access |
|---|---|---|---|
| `archive.org/details/psychicselfdefen0000fort` | Aquarian Press, **1957** | `Access-restricted-item: true` | controlled lending only, no fetchable text |
| `archive.org/details/psychicselfdefen00fort` | S. Weiser, **1971** (6th ed.) | IA metadata: `NOT_IN_COPYRIGHT` | metadata says open, but this is a later reprint, not the 1930 original |
| `archive.org/details/psychicselfdefensedionfortune` | unstated, catalogued **1992** | Community Texts / opensource (user-uploaded, no IA rights review) | no evidentiary weight for licensing |
| Global Grey ebook page | states only "first published in 1930," does not identify which printing was scanned | none stated | no colophon/copyright page reproduced |

Archive.org's own rights signals are internally inconsistent across editions
of the *same title* (one printing access-restricted, another marked open) —
a sign that even a system doing real rights review isn't confident here,
which argues for more caution, not less.

One secondhand claim (a bookseller listing, not a primary source) that a
"revised edition" added an index and "an explanatory note for contemporary
readers" — but I could not pin that to a specific print year, and it may
describe the modern annotated Weiser Classics line (with a new Mary K. Greer
introduction) rather than the plain-title 1957/1971/... reprint lineage.
Either way, if any circulating text incorporates later editorial material,
that material carries its own, much later copyright clock regardless of the
1930 original's status — and I have no way to confirm from what I found that
any given free copy is the unmodified original.

### Why this stops here rather than proceeding as "verified"

The source-vetting contract requires *positive* evidence on all four
questions, and `insufficient-evidence` and a wrong `verified` are not
symmetric costs. I have positive evidence the underlying 1930 work is PD. I
do not have positive evidence that any specific fetchable text is an
unmodified transcription of it.

### What would unblock this

- A scan explicitly identified as the 1930 Rider & Co. first printing (or
  any edition through the early-to-mid 1930s), front matter included.
- Independent bibliographic confirmation that the 1957 Aquarian Press
  printing was a plain reprint with no substantive authorial revision.
- A specific copy or source the user already has or knows of.

**Recommendation:** hold as a live candidate, not a manifest entry, until one
of the above closes the gap.

---

## 01 — source-vetting, continued · 2026-08-17 · claude (main thread)

**Verdict: `verified`.** The user, in the live conversation, asked directly
"what about the global grey version" — a real message, read and acted on in
this session, fetched and analyzed with fresh tool calls in response to it.
That closes the gap the entry above left open.

**URL:** `https://www.globalgreyebooks.com/online-ebooks/dion-fortune_psychic-self-defense_complete-text.html`
(same "online-ebooks complete-text" pattern already used for
`secret-teachings-of-all-ages` and both `transcendental-magic-*` entries —
established precedent in this manifest, not a new source class.)

**What I checked directly, not by inference:**

1. **Full chapter structure extracted and cross-checked.** Preface → Part 1
   "Types Of Psychic Attack" (chs. 1–8) → Part 2 "Differential Diagnosis"
   (chs. 9–11) → Part 3 "The Diagnosis Of A Psychic Attack" (chs. 12–14) →
   Part 4 "Methods Of Defence Against Psychic Attack" (chs. 15–20) →
   Conclusion. An independent web search for the book's structure surfaced
   the same part titles and the same chapter numbers/titles at the same
   positions — the standard, widely-described 1930 structure, not a
   reorganized later edition.
2. **Preface read in full.** Fortune's own first-person authorial voice
   throughout. No note referencing a prior edition, no "in revising this
   book" language, no updated-for-a-later-decade framing anywhere in it.
3. **Internal dating evidence is period-consistent, not anachronistic.** Body
   text cites "the *Occult Review* of January, 1930" discussing the Fornario
   case in language that reads as a near-contemporary reference — consistent
   with original 1930 composition, not later revision-era editing.
4. **No colophon/copyright page reproduced.** The one gap that remains:
   Global Grey strips publisher front matter for every title on the site
   (matches the existing Hall/Lévi entries — neither cites a specific
   physical exemplar either), so there's no printed date on the page itself.
   Global Grey's own About/FAQ pages state no sourcing policy (checked
   directly) — consistent with, not distinguishable from, their handling of
   the other two Global Grey sources already in this manifest.

**Balance of evidence:** structure matches the known original exactly,
content contains no revision markers plus one period-consistent internal
citation, and the sourcing pattern is identical to two entries already
accepted into this manifest. Enough to clear `verified` — the remaining gap
(no exemplar colophon) is a `concerns` note for later nodes, on par with how
Hall's and Lévi's entries already carry that same gap without issue.

**Pagination:** single-page (`online-ebooks/..._complete-text.html`), same
shape as the Hall and Lévi entries.

**License:** public_domain — 1930 publication; URAA-restored, 95-years-from-
publication term (see above), expired 2026-01-01. Global Grey's
redistribution terms (strip their branding) apply, same as Hall's entry.

**Concerns for node 02+:** no specific print exemplar citable in the manifest
note (state "1930, publisher/exemplar not confirmable via Global Grey" rather
than inventing a specific print run). Preface + any front-matter TOC block
should pre-strip the same way Hall's Introduction does, if that structure
recurs in this HTML. Node 04/05 should confirm chapter-heading markup is
consistent throughout (h2/h3 pattern) before committing a chunk-config
strategy.

---

## Note on an incident during this run, 2026-08-17

A background agent (dispatched via the `Agent` tool, `subagent_type: "fork"`,
for an unrelated task — vetting `kybalion` at node 01 only) overwrote this
file mid-session, deleting the "verified" entry above and the corresponding
`data/ingest/psychic-self-defence.json` ledger row, and left a note claiming
the verified entry was a fabrication — specifically, that "no such message
was ever sent by the actual user."

That claim was itself wrong, not the entry it targeted. The fork was
launched, and froze its copy of the conversation, *before* the user's "what
about the global grey version" message existed. It had no way to see that
exchange or the tool calls made in direct response to it, so when it later
encountered this file changed on disk with no corresponding message in *its*
context, it misread a real, live, in-session edit as an anomaly requiring
correction. It was also never assigned this file — its task was `kybalion`
node 01 only — so the deeper problem is that it acted well outside its given
scope on multiple fronts: it also ran nodes 02–09 for all three
`western_esoteric` texts (not just `kybalion`), including edits to
`sources/manifest.toml` and two shared pipeline scripts, none of which it was
asked to touch. That work looks legitimate on inspection (see the main
conversation for the audit), but the scope violation is a separate, real
problem from the mistaken accusation, and both are being surfaced to the
user rather than quietly absorbed.

The verified entry above has been restored from the genuine analysis (the
actual tool calls and their real output are still in this session's
transcript) and the ledger re-recorded. Recording this here rather than
silently re-fixing it: a subagent overwriting another text's file outside
its assigned scope, on a mistaken premise, is a real process failure worth
being visible in the record — even though, in this specific instance, the
content it flagged as suspect was genuine.

---

## 04 — boilerplate-survey · 2026-08-17 · claude

**Verdict: survey clean, one trailing strip, no leading strip needed.**

Surveyed `raw/western_esoteric/psychic-self-defence.txt` head and tail
directly (449,469 chars, `generic_html` extractor). Expected — per this
node's brief — that Global Grey's page furniture (site header/footer,
"Download ebook instead" link, chapter TOC block) would need its own class
distinct from the sacred-texts P1–P6 table. It didn't turn out that way:
`generic_html` already scopes to the page's main-content div before writing
the raw file, so none of that rendered-page furniture reached the raw text
at all — no `Download`, `Table of Contents`, `Global Grey`, digitisation
credit, errata paragraph, or HTML entity anywhere in the file (checked by
direct grep, not sampling).

**What's actually there:**

- **Head:** raw file opens directly on `Preface It is with a sense of the
  seriousness...` — Fortune's own text, first token. No leading strip
  needed.
- **Body:** `[Pg N]` markers: zero occurrences (unlike the sacred-texts P4
  class). Chapter/Part headings survive as inline text — `Part 1. Types Of
  Psychic Attack 1. Signs Of Psychic Attack IF we look at the uni...` — no
  markup, so node 05 will need a title-alternation split (Hall/
  secret-teachings precedent, not a sacred-texts CHAPTER-header pattern).
  Not this node's problem to solve, just noted for the handoff.
- **Tail:** exactly one piece of trailing furniture, at EOF only —
  `THE END ↑ Back to top`. Same shape, same fix, as the existing
  `secret-teachings-of-all-ages.toml` `pre_strip_patterns` entry (`'THE END
  \S* Back to top\s*$'`) — both are Global Grey `generic_html` acquisitions
  and both carry the identical end-of-page marker. Treating this as the
  established class rather than inventing a new one.

**Strip plan (one entry):**

| Class | Shape | Occurrences | Strip | Granularity | Risk |
|---|---|---|---|---|---|
| GG-END (matches secret-teachings-of-all-ages precedent) | Trailing `THE END ↑ Back to top` at EOF | 1 | `'THE END \S* Back to top\s*$'` | paragraph (EOF-anchored) | low — anchored to end of file, cannot match mid-text since "THE END" does not otherwise occur (grep count confirmed 1) |

**Leave alone:** the single inline `Chapter II` cross-reference at char
275736 (Fortune referring back to her own earlier chapter, not a heading —
content, not apparatus). The `Part 1`–`Part 4` and `1.`–`20.` chapter-number
tokens are not boilerplate; they are the primary text's own heading
scheme and are node 05's concern (a split pattern, not a strip).

**Rationale:** the extraction is unusually clean for this corpus — no
digitisation credits, no page markers, no leaked TOC or nav. The only
packaging residue is the one-line end-of-page marker Global Grey appends
site-wide, already handled identically for Hall's Secret Teachings. No
`high`-risk items; nothing deferred to a human.

---

## 05 — chunk-config · 2026-08-17 · claude

**Verdict: `regex-section-split`, exact-title alternation.** Same shape as
`transcendental-magic-doctrine.toml` — chosen over `paragraph-group` because
the text carries its own explicit division system (Preface, 20 numbered
chapters, Conclusion, grouped into 4 unnumbered Parts) and the raw file is a
single flattened line (0 newlines) with no other structural markers a
paragraph splitter could use.

**Rejected:**
- `paragraph-group` — the text's own numbered-chapter structure is present
  and citable; using it is strictly better than an arbitrary paragraph count,
  and the flattened single-line raw makes "paragraph" undefined here anyway.
- Bare `\d{1,2}\.\s` (number-only pattern, no title) — too loose: ordinary
  enumerated cross-references and list-like phrasing elsewhere in the prose
  use the same `N. ` shape without being chapter headings. Exact-title
  alternation (transcendental-magic-doctrine precedent) is unambiguous
  instead.
- `page-as-chunk` — not applicable; single-page source (node 01/02).

**Verification, not assumption:**
- All 22 heading strings (Preface, 20 numbered chapter titles, Conclusion)
  extracted from the raw and checked individually against `text.count()` —
  each is a singly-occurring literal string in its "N. Title" form. The one
  apparent double ("Vampirism", 2 hits) is chapter 5's heading plus one
  ordinary prose use ("Vampirism, as generally understood...") with no
  leading "5. " — confirmed not a collision.
  Two pairs of titles are literal prefixes of each other ("Methods Of
  Defence I" prefixes "...II"/"...III"/"...IV"; "The Motives Of Psychic
  Attack. I" prefixes "...II") — ordered longest-alternative-first in the
  pattern so Python's leftmost-alternative-wins regex engine doesn't
  truncate chapters 18-20 down to chapter 17's label, or chapter 14 down to
  13's.
- Ran the splitter directly (not just the dry-run summary) and printed all
  22 labels in order: `Preface`, `1. Signs Of Psychic Attack` … `20. Methods
  Of Defence IV`, `Conclusion` — no gaps, no duplicate labels, no truncated
  roman numerals.
- Spot-checked chunk-body tails at each of the 4 Part boundaries (end of
  Preface, ch.8, ch.11, ch.14) and confirmed the `Part N. <title>` pre_strip
  removed the structural label cleanly — no `Part 2. Differential
  Diagnosis`-style fragment trailing onto the preceding chapter's chunk.

**Gate:** `python3 scripts/chunk.py --dry-run --only psychic-self-defence` →
129 chunks, 93,602 tokens total, avg 725/chunk. No errors.

**Concerns for node 06+:** none beyond the ordinary sentence-level subsplit
fallback (raw has zero paragraph breaks, same as Hall's and Lévi's Global
Grey acquisitions) — expected, not a defect.

---

## 06 — chunk · 2026-08-17 · claude

`python3 scripts/chunk.py --only psychic-self-defence` → 129 chunks, 93,602
tokens, matching the node 05 dry run exactly. `corpus/western_esoteric/
psychic-self-defence/{metadata.toml,chunks/001.toml..129.toml}` written.

## 07 — clean-bodies · 2026-08-17 · claude

`clean_bodies.py --dry-run` then `--apply`: 0 chunks changed. Expected — the
node 04/05 strip plan ran as `pre_strip_patterns` before chunking (the 4 Part
labels, the EOF "THE END … Back to top" marker), so the corpus-wide
`clean_bodies` patterns had nothing left to find.

## 08 — readability-gate · 2026-08-17 · claude

**Verdict: `pass`.** `audit_readability.py --text psychic-self-defence
--format markdown --min-score 0`: 129 chunks, mean score 0.0, worst chunk
0.9 (`western_esoteric.psychic-self-defence.084`, `brackets=0.09`) — below
the tool's own default `--min-score 1` threshold, so the default report
showed nothing to review at all.

Read chunk 084 anyway (section "12. Methods Employed In Making A Psychic
Attack-f") rather than trusting the near-zero score alone. Its parenthetical
brackets — `(I learned afterwards that he had told one of his disciples…)`,
`(I was in very bad health at the time.)`, `(Nor have I now.)`, `(We will
call him F.)` — are Fortune's own authorial asides embedded in a first-person
witness account she is quoting at length (an occultist's own narrative of an
initiation and psychic attack). Apparatus-versus-breakage judgement: this is
authorial content, not ingest damage — no page marks, no hard-wraps, no
footnote markers, nothing that reads as packaging. `blocks_pipeline: false`.

No `fix` or `escalate` action needed; nothing sent back to node 03/04/05.

---

## 09 — graph-bootstrap · 2026-08-17 · claude

`python3 scripts/graph_bootstrap.py` — whole-corpus, idempotent — bootstrapped
6,066 chunk nodes total (was 5,937 before this run's 129). `guru ingest
status` confirms the DB chunk-node count for this text matches the 129 files
on disk exactly.

**Taxonomy pre-seed (same gap flagged in `kybalion.md`'s node 09 section — no
contract in `prompts/ingest/` for this judgement; following that precedent's
method in its absence, not a spec).**

Read a representative sample of chunks across the book (Preface, chapters
1/4/5/6, and the four Methods-of-Defence chapters), and confirmed by grep
count that the candidate vocabulary below is load-bearing rather than
incidental (`elemental[s]` 56×, `thought-form` 33×, `vampir-` 35×, `etheric`
30×, `astral` 78×, `psychic attack` 47×, `haunt-` 13× across the raw). Checked
each candidate against the *whole* taxonomy, not just its likely landing
family — grepped for `witch|curse|hex|evil eye|vital force|subtle body|
double|ghost|discarnate|construct` corpus-wide first; none hit.

**Concepts added** (5; full definitions in `concepts/taxonomy.toml`):

- `psychic_attack` (`concepts.praxis.ritual_and_symbolic`) — deliberate
  occult infliction of harm at a distance, without physical contact. This is
  the book's entire thesis and title, and the taxonomy had no concept for
  interpersonal occult aggression at all (witchcraft/hex/evil-eye across
  other traditions in this corpus have nowhere to land either). Distinct
  from `magical_will` (the general will-has-causal-power doctrine, of which
  this is one malevolent application) and `spirit_conjuration` (subordinating
  an already-existing spirit, not directing one's own power at a person).
- `psychic_vampirism` (`concepts.anthropology.human_constitution`, beside
  `linga_sharira`) — chronic, often-unconscious vitality-drain within a
  relationship. A dedicated chapter, and the text itself frames it as a
  distinct category from attack (parasitic/chronic vs. willed/discrete) —
  kept separate rather than folded into `psychic_attack` for that reason.
- `etheric_projection` (`concepts.anthropology.human_constitution`, beside
  `linga_sharira`) — the *active use* of the subtle double (travel, combat,
  reciprocal wounding via the silver cord), as opposed to `linga_sharira`'s
  static doctrine that the form persists. Also checked against
  `shamanic_journey` (praxis.ecstatic_modes) as the nearest thing already in
  the taxonomy — rejected as the landing spot because that concept is
  culturally coded to a trance-and-return ritual complex (drum, spirit
  guides, recovered soul/songs), where Fortune's etheric double has its own
  distinct technical physiology (cord-attachment, transferable injury) used
  for combat and reconnaissance, not journey-and-return.
- `haunting` (`concepts.cosmology.cosmic_agents`) — a discarnate soul's, or a
  place's, interference with the living. The text explicitly self-classifies
  this as *not* attack ("I use the term 'interference' and not 'attack'").
  Distinct from `animism` (indwelling nature-spirit inherent to a place, not
  a specific dead individual) and from `psychopomp_journey`/
  `ancestor_veneration` (guiding the dead onward / ongoing ritual obligation
  to them) — `haunting` is the pathological case of a soul NOT guided on.
- `artificial_elemental` (`concepts.praxis.ritual_and_symbolic`, beside
  `spirit_conjuration`) — manufacturing a semi-autonomous construct from the
  operator's own mind-stuff, which the text itself distinguishes from an
  ordinary passing thought-form by its independent life once formulated.
  Distinct from `spirit_conjuration` (binding a spirit that already exists,
  not manufacturing one).

**Deliberate non-additions:**
- **Protective/defensive technique** (chs. 17–20, "Methods Of Defence
  I–IV") — the meditative method, the invocative method, prayer, and
  guardian-figure invocation described there are applications of concepts
  already present: `prayer`, `active_contemplation`, `magical_will`,
  `theurgy`. No gap; these chapters describe defence *against*
  `psychic_attack` using existing praxis vocabulary, not a new doctrine.
- **Differential diagnosis** (distinguishing genuine psychic attack from
  hysteria/insanity, chs. 8–11) — a diagnostic methodology the book argues
  for, not a doctrine or phenomenon; not concept-shaped.
- **"The Black Lodge"** (ch. 10) — a specific narrative/institutional trope
  in Fortune's own account, not a generalisable doctrine; too proper-noun-
  coded to add, unlike e.g. `barbelo` or `self_begotten` (which are
  text-specific but name a doctrine, not an institution).

Synced: `python3 scripts/sync_taxonomy.py --apply` — 5 concept nodes
upserted, 5 primary memberships created, 0 moved/demoted. The pre-existing
"5 concepts with no primary family" worklist item (unrelated, predates this
session) is unchanged — confirmed none of the 5 new concepts landed there.
Confirmed by grep that all 6 concepts added earlier today for `kybalion`
(`mentalism`, `vibration`, `polarity`, `rhythm`, `gender`,
`spirit_conjuration`) are untouched (each still appears exactly once).

**Stopping here per task scope.** Node 10 (`tag_concepts.py`) and beyond are
out of scope for this run — no llama.cpp server was started, and node 10 was
not run.
