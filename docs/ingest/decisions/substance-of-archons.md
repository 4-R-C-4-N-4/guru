# substance-of-archons — source vetting and ingest decisions

**Work:** *The Hypostasis of the Archons* (The Reality of the Rulers), Nag Hammadi Codex II, 4 — a Sethian Gnostic treatise critiquing the demiurge and the archontic rulers of the material world.

## The licensing problem

Two versions of this text on gnosis.org are **unusable** for this corpus:

1. **`http://www.gnosis.org/naghamm/Hypostas-Barnstone.html`** — the Barnstone & Meyer
   translation, © 2003 Willis Barnstone & Marvin Meyer. Explicitly copyrighted; the
   site states "Dr. Barnstone retains all copyright." (This is the URL the user
   originally flagged.)

2. **`http://www.gnosis.org/naghamm/hypostas.html`** — the Bentley Layton translation.
   The gnosis.org footer on every CGLP text reads: *"E. J. Brill has asserted
   copyright on texts published by the Coptic Gnostic Library Project."* The Layton
   translation is part of the copyrighted Coptic Gnostic Library (Brill, 1989).

The earlychristianwritings.com mirror (`https://www.earlychristianwritings.com/text/archons.html`)
is the **same Layton translation** with the same copyright constraints — it is
sourced from the Brill CGLP edition, not independently PD.

## The public-domain source found

**`https://www.luminescence-llc.net/the-substance-of-the-archons`**

This is a **new English translation committed to the public domain** by Samuel
Zinner, edited by Mark M. Mattison, via the Other Gospels / LUMINESCENCE project.
The page states explicitly:

> "The following translation has been committed to the public domain and may be
> freely copied and used, changed or unchanged, for any purpose."

This matches the project's existing precedent for the **apocryphon-of-john** source:
a Zinner-Mattison synoptic translation dedicated to the public domain by the
translator, hosted outside a major archival institution. That source's decision
doc (see `docs/ingest/decisions/apocryphon-of-john.md`) records the same
"translation committed to PD by the translator" legal basis and the same
Caveat translator (Samuel Zinner, edited by Mark M. Mattison).

The nag-hammadi.net project (also Zinner + Mattison, also Other Gospels-supported)
hosts the full set of Nag Hammadi PD translations across `luminescence-llc.net`
and `othergospels.com`. The Archons page at othergospels.com was checked and
rejected — it carries an **additional** notice: *"The rendering of the above
scripture was made possible by Willis Barnstone, who has graciously provided
exclusive permission to present it here. All rights... are reserved by the
author."* That Barnstone-mediated version is copyrighted, not PD. The
luminescence-llc.net version is the **pure Zinner translation**, PD.

## Vetting

**Verdict:** verified.

**Source:** `https://www.luminescence-llc.net/the-substance-of-the-archons`

**Translator:** Samuel Zinner (edited by Mark M. Mattison). The translator
explicitly states the translation is "from the Coptic text in Bentley Layton, ed.,
*The Coptic Gnostic Library: Nag Hammadi Codex II,2-7* (Leiden: Brill, 1989)" —
i.e., the same underlying Coptic witness, rendered into a fresh English
translation that the translator has committed to PD.

**Licence:** public domain, stated in the page body:
*"The following translation has been committed to the public domain and may be
freely copied and used, changed or unchanged, for any purpose."*

**Pagination:** single page. The entire text (introduction through the concluding
"Amen" of the Epilogue) appears on one HTML page with no `Next:` link, no chapter
index, and no pagination markers. The Coptic page numbers (ccdl.claremont.edu
hyperlinks at [86]–[97]) are inline scholarly apparatus, not separate fetch
targets.

**Format:** HTML, single page, ~27,451 characters.

**Heading chain (structure):**
- `h1`: "The Substance of the Archons" / "NHC II, 4"
- Section-level headings (`h2`/`strong`):
  1. "Samael, the 'Blind God'" — the demiurge's error and fall
  2. "The Archons Create Adam"
  3. "The Garden of Eden and Eve"
  4. "The Serpent"
  5. "Adam and Eve's Children" (Cain, Abel, Seth, Norea)
  6. "The Flood"
  7. "The Archons Try to Rape Norea"
  8. "The Angel Eleleth"
  9. "The Origin of the Blind God" (the cosmogonic myth: Sophia, Yaldabaoth, Sabaoth)
  10. "Norea's Final Questions" (the Epilogue / soteriological payoff)
- `h2`: "Notes" — editorial footnotes [1]–[9]

**Confirmation that this is the right text:** The headings match the known
structure of the *Hypostasis of the Archons* — the Samael/Yaldabaoth demiurge
myth, the androgynous archons creating Adam, the Eve/serpent/Norea episode, the
Noah flood narrative, Eleleth's cosmogonic revelation, and the Epilogue where
the soul is told it originates "from the primeval father, from above." This is
not an introduction essay or apparatus.

## Acquisition structure

`format = "html"`, single page. The primary text lives inside
`<div class="main" ...>` (Squarespace default). The page header contains site
nav (logo, menu), the main nav links are in a sidebar, and the footer has nav
+ copyright. The **Notes** section (editorial footnotes [1]–[9]) is apparatus —
the driver should strip it at chunk time, as per project policy (apparatus is
not primary text; cf. apocryphon-of-john decision doc, where bracketed
translational commentary is similarly deferred to the Driver).

Coptic page-number hyperlinks ([86]–[97] linking to ccdl.claremont.edu) are
inline scholarly apparatus markers — these are **retained in raw** for
reproducibility but flagged in `notes` for the Driver to strip during
cleanup (clean_bodies / pre_strip). They are small and inline.

## Concerns for the Driver

- The **Notes** section (footnotes [1]–[9]) is translator/editor apparatus, not
  primary text. It contains etymological commentary and cross-edition
  comparisons — strip before chunking.
- The intro paragraph citing the four consulted translations is provenance, not
  text — strip.
- The section headings are marked by `<h2>` tags and bold paragraphs. The
  `<h2>` headings are the natural chunking boundaries (`regex-section-split`).
- The text contains many `[...]` lacunae markers and `(parenthetical)` editorial
  insertions — these are faithful to the Coptic witness and should be **kept**
  as part of the text (they are gaps in the source manuscript, not apparatus
  added by the translator for non-textual reasons). The bracketed **page-number
  links** are the only apparatus to strip.
- Title for corpus purposes: "The Reality of the Rulers" or "The Substance of
  the Archons". The existing corpus concepts that this text backs:
  `archons`, `demiurge`, `demiurge_sin`, `fall_of_sophia`,
  `emanation_hierarchy`, `pleroma` (already in taxonomy via apocryphon-of-john).
