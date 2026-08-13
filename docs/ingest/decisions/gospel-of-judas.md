# gospel-of-judas — source-vetting (node 01)

**Decision date:** 2026-08-12
**URL:** https://www.gospels.net/judas
**Tradition:** gnosticism
**Verdict:** `verified`

## What the page is

A single-page HTML translation of the Gospel of Judas (Codex Tchacos 3, Coptic)
by Mark M. Mattison, hosted on gospels.net. It is a real translation of the
primary text — the incipit ("This is the secret message of judgment Jesus spoke
with Judas Iscariot…") and the Sethian content follow immediately under an h1
"The Gospel of Judas" / h3 "by Mark M. Mattison" byline.

## Evidence for the four questions

1. **Translation, not apparatus.** The heading chain is `Gospel of Judas —
   Gospels.net` / `The Gospel of Judas` / `by Mark M. Mattison`, and the body is
   the translation itself, not an introduction essay. The "Notes on Translation"
   section at the end is translator's apparatus, but it is a tail, not the page.
2. **Right work, right edition.** The page names the work and translator it
   claims. This is a Mattison translation, consistent with the existing
   `apocryphon-of-john` entry (Zinner/Mattison), which carries the same
   public-domain dedication sentence.
3. **Single-page.** One HTML page holds the full text. The Codex Tchacos
   pagination (33–58) is present inline as bold page markers — *not* as separate
   pages and *not* as section boundaries.
4. **License: public domain.** Positive evidence — explicit dedication in the
   body: "committed to the public domain and may be freely copied and used,
   changed or unchanged, for any purpose." Format `html`.

## Concerns for later nodes

- **Section headings are centered `<strong>` paragraphs, not real heading tags.**
  The chunker must split on those title lines, not a `heading` strategy that
  matches `<h1–h6>`.
- **Page numbers 33–58 are inline within sentences** (e.g. `…his disciples
  <strong>34</strong> sitting together…`). They are the manuscript pagination
  and should survive as content; they cannot be used as clean chunk boundaries
  and must not be misread as numbered sections.
- **"The Gospel of Judas" appears twice** — as the h1 page title *and* as a
  section heading in the body (the actual translation section). A regex splitter
  must not conflate the two.
- **The site nav menu is emitted twice** (desktop + mobile) plus a footer; the
  translator's book promo + affiliate disclosure sit in the intro. Node 04 strip
  plan required; `generic_html` may not auto-strip it (content is in plain
  `<p>` blocks, likely not a `<main>`/`article`/content-class container).
- **gospels.net is not in the downloader registry** — acquisition falls to
  `generic_html.py` (node 02 must verify its output).
- **The translator's "Introduction" section is content, not apparatus** — the
  Gospel of Judas genuinely opens with the "secret message of judgment" incipit.
  Do not strip it as front matter.

## Provenance

Raw HTML fetched 2026-08-12 (77 KB, HTTP 200). Structure analysed by hand.

---

# gospel-of-judas — nodes 04–08

**Nodes 04, 05, 06, 07, 08 driven 2026-08-12** (feat/judas branch).

## 04 — boilerplate-survey

Front matter identified and stripped at the chunker config (pre_strip) rather
than via clean_bodies: the h1 title + byline ("The Gospel of Judas by Mark M.
Mattison"), the public-domain notice + translator's book promo (affiliate
disclosure), and the Symbols legend ("... ( ) Editorial insertion"). The
doubled site nav (desktop + mobile) plus footer menu was already removed by
generic_html (nav/footer/menu tags) — verified absent from the raw. The
translator's "Introduction" section is CONTENT (the text's real incipit), not
front matter; kept.

**CORRECTION (2026-08-12, after review):** the initial version of this node
kept the "Notes on Translation" tail as two chunks (009/010) to be left
untagged at node 11. That deviated from project policy — the sibling texts
strip translator's apparatus at chunk time: apocryphon-of-john.toml strips
its "Translator's notes" block verbatim ("scholarly apparatus per project
policy (cf. gilgamesh-tablet-*.toml, pistis-sophia.toml). Kept in the raw
file, stripped before chunking"), and pistis-sophia.toml strips the
PREFACE/CONTENTS/INTRODUCTION and INDEX blocks. gospel-of-judas was the only
text in the corpus with notes chunks. Fixed: the config now pre-strips
`\s+The Gospel of Judas\s+Notes on Translation[\s\S]*$` (which also removes
the empty "The Gospel of Judas" heading before it), the text re-chunked to 8
chunks, and all DB rows referencing the vanished 009/010 (staged_tags,
review_actions, embeddings, tagging_progress, edge_progress, staged_edges
negatives, nodes, BELONGS_TO edges) were deleted in a transaction. The 22
reject verdicts queued on those chunks were removed with their rows — the
queue is now 239 (105 accept / 134 reject).

## 05 — chunk-config

`chunking/gnosticism/gospel-of-judas.toml`, strategy `regex-section-split` on
the translator's section titles (each verified unique, case-sensitive, in the
raw). Section labels become the citations: Introduction / Jesus Criticizes the
Disciples / Another Generation / The Disciples' Vision / Jesus and Judas /
Jesus Reveals Everything to Judas / The Betrayal / Notes on Translation.

**Bug caught and fixed at this node:** the first pattern used the prefix
"The Disciples" + `\s+` to dodge the apostrophe in "The Disciples' Vision"
(TOML literal-string constraint). The splitter silently missed the section —
after "The Disciples" comes an apostrophe, not whitespace — so "The Disciples'
Vision" content was absorbed into "Another Generation" (which then sub-split,
hiding the problem). The pattern is now a double-quoted TOML basic string
matching the full title "The Disciples' Vision" verbatim (`\\s` doubled). The
silent-merge failure mode from the yoga-sutras regex splitter is exactly what
happened here; the count-check discipline caught it.

## 06 — chunk

8 chunks, 8 sections (2 sections sub-split past 800 tokens: "Jesus Reveals
Everything to Judas" into -a/-b). Corpus files in
`corpus/gnosticism/gospel-of-judas/`. Verified: no nav/menu/book-promo leakage
in any body; front matter gone; page markers (33–58) preserved inline as
manuscript pagination; "The Betrayal" tail clean (the empty "The Gospel of
Judas" heading and the "Notes on Translation" apparatus tail are pre-stripped
— see the node 04 correction; the text initially chunked to 10 including two
apparatus chunks, re-chunked to 8 after the policy correction).

## 07 — clean-bodies

`clean_bodies.py --dry-run` reports 0 changes: bodies are already clean because
all stripping happened at the chunker config. Nothing further to apply.

## 08 — readability-gate

`audit_readability.py` reports mean 7.9 / worst 10.0 on `brackets` (1.00 on
three chunks). **Verdict: pass.** This is the fragmentary-manuscript case from
the node 08 failure modes (Gilgamesh tablets precedent): the Codex Tchacos
text has lacunae, and `[ ]` / `( )` / `[…]` are the source's own gap and
editorial-insertion markers, faithfully kept by the translator. They are
content, not ingest damage. No acquisition damage observed (no split words,
no hard wraps, no page-break artifacts).

## Next-node blockers (09+)

- **09 taxonomy gap:** the text's Sethian cosmology concepts — Barbelo, the
  Self-Begotten (Autogenes), the luminaries, Nebro / Saklas, the "great
  generation", the star-astrology and the thirteen — are absent from
  `concepts/taxonomy.toml` (archons and demiurge/yaldabaoth exist). Without
  additions, node 10 produces a tag pool dominated by `is_new_concept`
  proposals, which node 11 flags as a much harder review.
- **10 tag-concepts:** requires starting a llama.cpp server with
  Qwen3.5-27B-UD-Q4_K_XL.gguf (on disk, 17.6 GB). GPU currently idle.
- **11/14:** review queues, human apply. **15:** user.

---

# gospel-of-judas — node 09

**Node 09 driven 2026-08-12** (feat/judas branch).

## graph-bootstrap

`graph_bootstrap.py` run — whole-corpus, idempotent. 5,707 nodes / 55,309 edges
(5,569 chunks bootstrapped). The 10 gospel-of-judas chunk nodes verified in
`nodes` (`gnosticism.gospel-of-judas.*`, count = 10).

## Taxonomy additions

Six concepts added to `concepts/taxonomy.toml` and synced
(`sync_taxonomy.py --apply`; 116 concept nodes upserted):

| concept | family | why |
|---|---|---|
| `barbelo` | cosmology.divine_structure | the "immortal realm of Barbelo" (the text's origin of the mysteries) |
| `luminaries` | cosmology.divine_structure | the twelve/72/360 light-orders (the text's numeric hierarchy) |
| `stellar_determinism` | cosmology.cosmic_order | "the error of the stars" — the astral bondage the savior exposes |
| `incorruptible_generation` | soteriology.soteric_categories | the text's central soteriological claim (the strong, holy generation) |
| `self_begotten` | theology.divine_nature | the Self-Begotten (Autogenes), God of the Light |
| `rejection_of_sacrifice` | praxis.ritual_and_symbolic | the text's central polemic (sacrifice = service to Saklas) |

Also extended `demiurge` aliases with `saklas` and `nebro` (the text names
Nebro "Rebel," "others call him Yaldabaoth").

These are deliberately tradition-agnostic structural definitions (the tagging
layer is tradition-agnostic; cf. node 11's cross-tradition rule), and each
carries a "distinct from" clause against the nearest existing concept so the
tagger can disambiguate.

## Deliberate non-additions

- No `thirteenth` concept: "you'll become the thirteenth" is a single-text
  detail of Judas's exclusion, better tagged to `incorruptible_generation`
  than given its own node.
- No `seth`/`seed` concept: the seed-of-Seth language is covered by
  `incorruptible_generation` (the text's own phrasing is "the great
  generation").

## Model choice: 27B teacher over the v3 finetune (deliberate)

The rellm repo (`~/Work/rellm`) has a current v3 tagger finetune
(`out/qwen3-4b-guru-v3-r32/gguf/qwen-3-4b-guru-v3-Q4_K_M.gguf`), which beats
v1/v2 on every benchmark metric. It was NOT used for this text, and that is the
point, not an oversight:

- v3 is pinned to the 110-concept taxonomy snapshot it trained on (its
  `taxonomy.toml`). Its OOT-ID behaviour in the v3 benchmark — 2 out-of-
  taxonomy concept proposals vs the base model's 15 — shows it stays inside
  its training set.
- This text's central concepts are precisely the six added at node 09
  (barbelo, self_begotten, luminaries, stellar_determinism,
  incorruptible_generation, rejection_of_sacrifice), which postdate v3's
  training taxonomy. v3 would tag the 110 known concepts and silently miss the
  text's core.
- The 27B teacher reads the live taxonomy fresh in-prompt, so it proposes the
  new concepts natively. Confirmed live: chunk 002 got barbelo:3,
  incorruptible_generation:2, rejection_of_sacrifice:2, stellar_determinism:2;
  chunk 003 got incorruptible_generation:3.

Rule of thumb for future texts: the finetune is the right tagger when the
text's key concepts are within its pinned taxonomy snapshot; the 27B teacher
is the right tagger for any text whose concepts postdate that snapshot. A v3
run against the live (116-concept) taxonomy would be a fair comparison only
for texts that predate the six additions.

---

# gospel-of-judas — nodes 10–13

**Nodes 10, 12, 13 driven 2026-08-12** (feat/judas branch).

## 10 — tag-concepts

Qwen3.5-27B-UD-Q4_K_XL.gguf on the 3090 (port 8080, serve-llama.sh). 10/10
chunks, 261 tags, 0 errors, 0 parse failures. Score distribution: 42× score 3,
113× score 2, 106× score 1. Coverage gate satisfied (10/10 rows in
`tagging_progress`). All six node-09 concepts proposed with max score 3:
incorruptible_generation ×9, stellar_determinism ×8, luminaries ×7,
rejection_of_sacrifice ×3, barbelo ×2, self_begotten ×2.

## 12 — embed

`embed_corpus.py --resume --text gospel-of-judas` — 10 rows in
`chunk_embeddings` (nomic-embed-text via Ollama).

## 13 — propose-edges

Mistral-Small-3.2-24B on the 3090 (port 8080). 29 PARALLELS proposals
(1× 0.90, 28× 0.85) + 13 negatives persisted (11 unrelated, 2 surface_only),
0 errors. Partner traditions: jewish_mysticism (Enoch) ×26, mandaean ×3,
sufism ×2, zoroastrianism / taoism / neoplatonism ×1 each. The Enoch
dominance is expected — the Watchers/archons substrate and the heavenly
temple vision are the text's direct substrate (cf. `watchers_descent` in the
taxonomy).

## Remaining gates (user's)

- Node 11: 261 pending tag verdicts (42/113/106 at scores 3/2/1).
- Node 14: 42 staged edge rows (29 PARALLELS + 13 negatives).
- Node 15: publish. Branch is feat/judas; PR + apply + ship are the user's.

---

# gospel-of-judas — dossier chapter (Pass D, c7)

**D1–D5 driven 2026-08-12.** All ingest queues applied first (239 tags + 29
edges → 105 live EXPRESSES + 24 live PARALLELS).

## Campaign bump (V9)

gospel-of-judas is a NEW work → `campaign_id` bumped c6 → c7 in
`config/dossiers.toml` (never a partial re-plan). The c7 plan also picks up
apocryphon-of-john + yoga-sutras-book-01..04 (all ingested after c6 froze):
64 works / 794 spans / 13 degenerate. Prior 58 works' span ids unchanged; their
c6 staged rows carry forward.

## D1 plan-freeze

`build_dossiers.py --plan` → `docs/summary/span-plan-c7.{json,md}`.
gospel-of-judas is **degenerate** (single span "Introduction – The Betrayal",
all 8 chunks, 4,175 tokens) → skips L1/structure, goes straight to one L2.

## D2 generate — agent-driven with the driving-model convention

The user's call: generate this dossier with the present model rather than the
campaign default (claude-opus-4-8), recording the driving model in the
provenance line exactly like review verdicts. The guru pipeline's providers
(llamacpp/ollama/anthropic/openai/claude-code) have no "agent" provider, so
the agent drove the templates directly (the workbook's harness-neutral path)
and inserted rows with `model = "hermes-deepseek-v4-flash"`.

Rows: 1 L2 (`sum:gospel-of-judas`, l1-v2 rules, budget 347 → 415 tokens after
three compression passes against the cl100k counter) + 5 fields
(summary-v1, context-v1, figures-v1, terms-v1, notes-v1). The degenerate L2's
prompt_version is l1-v2 per `stage_l1`'s degenerate branch.

## D3 review — the flash model got caught by the grounding standard

The review is where the risk showed, and the loop worked as designed:

- **ACCEPT:** L2 (grounded in the primary text) and summary (classification +
  contents, significance correctly omitted — curator's notes are silent).
- **REJECT (GROUND) ×4:** context, key_figures, key_terms, reading_notes all
  carried details drawn from chunk-reading knowledge BEYOND their stage
  inputs: context's "fragmentary, gaps marked by brackets" (not in the
  curator's notes or L2), figures' "face flashes with fire / six angels /
  likeness / Michael and Gabriel / lifespans" (text-level, absent from the
  compressed L2), terms' "Autogenes" transliteration (came from the STRIPPED
  Notes on Translation — a genuine leak), notes' fragmentary + Codex-page
  claims. "Correct is not the standard. Supported by the input is." — the
  rubric's exact failure mode, reproduced by the flash model.
- **Regenerated strictly from stage inputs:** context drops the fragmentary
  claim and states the dating absence honestly; figures/terms glosses trimmed
  to L2-supported content (Autogenes → null transliteration); notes became
  `{"body": null}` (single-section outline speaks for itself). All re-accepted.
- Not a template defect (the failure was generator grounding, not template
  shape) — no template revision; the reject→regenerate loop is the audit trail.

Reviewer stamped `hermes-deepseek-v4-flash` (the CLI's default `agent` was
overridden to match the provenance convention).

## D4–D5

`promote_dossiers.py --work gospel-of-judas` (--dry-run first) → live
`work_dossiers` row (structure_json `[]` for the degenerate work, themes_json
from the live EXPRESSES edges: cosmic_dualism, gnosis_direct_knowledge,
hidden_sayings, incorruptible_generation, stellar_determinism, archons,
demiurge, eschatological_judgment) + `summary_nodes` L2.
`embed_summaries.py --resume` → 1 summary_embedding (768-dim, nomic-embed-text).

## D6 (user)

Export/ship is the user's gate, as node 15. `export.py` raises on any
unembedded summary node — none remain.

## Takeaway

The agent-model provenance convention extends to dossiers: `model` =
`hermes-deepseek-v4-flash` on every generated row, `reviewed_by` on every
verdict. The flash model produced acceptable L2 + summary on the first pass and
drifted on grounding in 4 of 5 detail rows — caught by D3, fixed by strict
regeneration. That is the honest answer to "is the present model good enough":
yes for this simple text, with the review gate doing its job.




