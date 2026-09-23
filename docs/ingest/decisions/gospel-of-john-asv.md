# gospel-of-john-asv — ingest decisions

Ingested with Genesis and Revelation on `feat/biblical-tradition`. The shared
reasoning — licence (ASV `usx-english-only` = public domain, aligned trees are
CC-BY), the `usx` downloader, and the `regex-section-split` + `group_by="tokens"`
verse-range chunk strategy — is in
[`genesis-asv.md`](genesis-asv.md). Only John-specific decisions are here.

---

## 01/03 — the 878-verse count is correct, not damage · 2026-09-21 · claude

John extracts to **878 verses, not the commonly-cited 879.** The ASV is a
critical text and relegates **John 5:4** ("for an angel went down at a certain
season into the pool, and troubled the water…") to the margin — so the USX
carries no `JHN 5:4` verse milestone, and the extractor correctly emits nothing
there. The node-05 sequence check found exactly one in-chapter gap, at 5:4, and
nothing else. This is the workbook's canonical failure-mode inversion: a
"missing" verse that is a legitimate textual decision, not extraction damage.

The **pericope adulterae (7:53–8:11)** *is* present in the ASV body (chapters 7
and 8 are contiguous with no gap). It is retained.

21 chapters. Recorded so a future reader who counts 878 against a KJV's 879 does
not go looking for a bug that is not there.

---

## 04–05 — chunk-config · 2026-09-21 · claude

Same shared strategy as Genesis. **37 chunks**, token min/median/max =
43/782/800. The 43-token final chunk is the single trailing verse
(`21:25`, "And there are also many other things which Jesus did…"), which stands
alone after the preceding group filled to the ceiling — expected, not a defect.

The Logos prologue (1:1–18) is the primary edge target against `plotinus-*`
(the Enneads' Logos material) and the Hermetica already in the corpus; it lands
inside the first one-to-two chunks.
