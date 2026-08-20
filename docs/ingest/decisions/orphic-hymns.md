# Orphic Hymns — drop Taylor front matter (re-chunk + remap)

Source-id: `greek_mystery.orphic-hymns`
Ticket: `df44bdeb` (child of `d1b3db8b`), corpus-quality intake sweep 2026-08-20

## What was wrong

The Thomas Taylor edition was chunked `page-as-chunk`, which kept every
sacred-texts.com page as a chunk — including Taylor's editorial front matter
(title page, Preface, and the "Dissertation on the Life and Theology of
Orpheus", raw pages 1–6). Those chunks carried **209 accepted concept tags**
and **528 source-side live edges**, all attached to editorial commentary
rather than the hymns. `flag_apparatus.py` lists them as candidates
(`orphic-hymns.001-034`, line 112) but its `has_surviving_tags()` filter skips
any chunk with accepted tags, so they escaped flagging.

## The correction to the ticket's scope

The ticket and the hand-off message both said "36 front-matter chunks", counting
`.001`–`.034` **plus `.087` and `.138`**. That was wrong in a way that would
have deleted a hymn:

- **`.087` is Hymn XLII "To the Seasons", not front matter.** Its body is the
  full 203-token hymn. It was labelled "Front Matter, p. 48" only because the
  source prints `XLII TO THE SEASONS` **with no period after XLII**, unlike
  every other hymn (`XLIII. TO SEMELE`), so `number_pattern '^([IVXLCDM]+)\.'`
  failed to match and it fell through to the no-number-match label. It carries
  **0 accepted tags** and sits correctly between XLI (.086) and XLIII (.088).
- **`.138` is a nav redirect page**, not a footnote block — body is "The new
  sacred-texts hypertext version of Homer's Iliad can be found here!...".

Net: **35 chunks dropped** (34 front matter + 1 redirect), **not 36**, and one
chunk relabelled rather than dropped.

## The change

`chunking/greek_mystery/orphic-hymns.toml`:

1. **`drop_before_marker = "TO THE GODDESS PROTHYR"`** — the front matter is a
   contiguous LEADING block, so the order-aware marker (drop every chunk before
   the first matching the first hymn's invocation) is the right tool. Anchor
   verified absent from all 34 front-matter chunks. **Not** `drop_chunk_patterns`
   on "FOOTNOTES"/"DISSERTATION": the hymns carry footnotes *inline* (54 chunks
   contain the word "Footnotes"), so that pattern would have deleted 54 real hymns.
2. **`drop_chunk_patterns = ["hypertext version of Homer"]`** — the one redirect
   page (.138), precise body-unique anchor.
3. **`number_pattern '^([IVXLCDM]+)\.'` → `'^([IVXLCDM]+)\.?'`** — the period is
   now optional, so Hymn XLII's missing period no longer sends it to the
   front-matter fallback. Bundles the relabel fix (Hymn XLII now labelled "Hymn
   XLII", unambiguous and citable; the title stays empty, consistent with the
   corpus's existing "Hymn X"/"Hymn XXV"-style title gaps where the source
   omits the period).

## Remap

`scripts/migrations/apparatus_remap.py greek_mystery/orphic-hymns` —
body-matched two-phase rename (pre-existing tool, CH-11 / Plotinus pattern).
Because `clean_bodies` was never run on this text (node 07 unrecorded), the
surviving hymn bodies are byte-identical between git HEAD and the re-chunk, so
the match was exact: **remap=103, delete=35**, zero residual TMP refs.

Consequence, and it is the correct one: the 209 accepted tags lived on the
**deleted** front-matter chunks, so the remap *deletes* them (with the chunks),
not re-points them — they are curation mistakenly applied to editorial prose,
and the whole point is to remove them. The **529 accepted tags** and the
surviving edges on the real hymns are preserved and re-pointed to the renumbered
ids. `graph_bootstrap --text orphic-hymns` refreshed section labels.

## CROSS-STREAM FOLLOW-ON (not part of this change)

The dossier stream (campaign c8, D1–D5 complete) was built **on the front
matter** — `work_dossiers.structure_json` has a span "Front Matter, p. 1–3" /
"Title Page, Preface, and Dissertation", and 6 of 13 L1 `summary_nodes` are
`front-matter-*` spans. `apparatus_remap.py` predates the dossier tables and
does not touch `summary_nodes`/`staged_summaries`/`work_dossiers`/
`staged_cleanups`, so those still reference the old (now renumbered or deleted)
chunk ids in the local DB. This is a freeze violation, not a remap: it needs a
**new campaign (c8→c9) and a full D1–D5 redo** for this work, owned by
corpus-quality, with the user's D3/D4 gates. Flagged to corpus-quality before
this change landed.