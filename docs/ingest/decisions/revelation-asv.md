# revelation-asv — ingest decisions

Ingested with Genesis and John on `feat/biblical-tradition`. Shared reasoning
(licence, `usx` downloader, verse-range chunk strategy) is in
[`genesis-asv.md`](genesis-asv.md). Only Revelation-specific notes here.

---

## 01/03 — acquire · 2026-09-21 · claude

22 chapters, **404 verses — contiguous, zero gaps.** No textual anomalies of the
John 5:4 kind. Clean extract.

---

## 04–05 — chunk-config · 2026-09-21 · claude

Same shared strategy. **22 chunks**, token min/median/max = 503/777/799 — the
tightest and most even distribution of the three books, because Revelation's
verses are uniformly dense with no long genealogies or short trailing fragments.

Verse-atomic-to-ceiling matters most here: Revelation's visions cascade across
verses, and a verse-per-chunk strategy would have shredded a single throne-room
or seals sequence into dozens of one-line fragments. Grouping to 800 keeps each
vision unit whole while the range label (e.g. `4:1-4:11`) preserves citation.

Revelation is the corpus's **"omega" anchor** to Genesis's "alpha". Its
apocalyptic counterpart material already in the corpus is thinner than the
cosmogony side — `enoch-charles-1917` and the Zoroastrian eschatological books
are the main edge targets — but it earns its place as the eschatological pole of
the biblical spine.
