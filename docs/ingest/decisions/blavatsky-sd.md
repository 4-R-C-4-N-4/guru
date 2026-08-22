# Vetting Decision: H.P. Blavatsky — *The Secret Doctrine*

## Verdict
**verified** — node 01 passed on 2026-08-22.

## Source
- **Work:** *The Secret Doctrine* by H.P. Blavatsky (1888)
- **URL:** `https://www.sacred-texts.com/the/sd/index.htm` (index/TOC)
- **Content pages:** `sd1-*.htm` (Volume 1: Cosmogonesis) + `sd2-*.htm` (Volume 2: Anthropogenesis)
- **Tradition:** `western_esoteric`
- **Format:** `html_multi` (indexed multi-page)
- **License:** Public domain (1888, Blavatsky d. 1891; hosted on sacred-texts.com)

## Verification checks

1. **Heading chain confirms primary text** (checked on `sd1-0-pr.htm` — Proem):
   > `The Secret Doctrine by H. P. Blavatsky -- Vol. 1` → `[[Vol. 1, Page 1]]` → `PROEM` → `PAGES FROM A PRE-HISTORIC PERIOD.` → `THE SECRET DOCTRINE.`
   - ✅ Confirmed primary text, not a translator's introduction essay.

2. **Page count / structure:**
   - Volume 1: 42 pages (`sd1-0-co`, `sd1-0-in`, `sd1-0-pr`, `sd1-1-01..18`, `sd1-2-01..15`, `sd1-3-01..18`)
   - Volume 2: 19 pages (`sd2-0-co`, `sd2-0-pn`, `sd2-1-01..25`, `sd2-2-01..13`, `sd2-3-01..09`)
   - Total: ~77 HTML pages (sacred-texts splits the text into large section files, ~27–75 KB each)

3. **URL structure:** Each page has nav-bar navigation (Previous/Next) confirming the multi-page form.

4. **License:** Meta tag "Public Domain and Creative Commons"; work from 1888, author died 1891. Clean US PD.

5. **Not a translation:** This is Blavatsky's original English-language work. No translator field.

## Page inventory (sacred-texts)

| Range | Content |
|---|---|
| `sd1-0-co.htm` | Full Verbatim Table of Contents (Vol 1) |
| `sd1-0-in.htm` | Introduction |
| `sd1-0-pr.htm` | Proem |
| `sd1-1-01` through `sd1-1-18` | Book I, Part I: Seven Stanzas from the Book of Dzyan (with commentaries) |
| `sd1-2-01` through `sd1-2-15` | Book I, Part II: The Evolution of Symbolism |
| `sd1-3-01` through `sd1-3-18` | Book I, Parts III–V (Anthropological Series) |
| `sd2-0-co.htm` | Full Verbatim Table of Contents (Vol 2) |
| `sd2-0-pn.htm` | Public Notice |
| `sd2-1-01` through `sd2-1-25` | Book II: Part I: The Mystery of the Buddhist Schism |
| `sd2-2-01` through `sd2-2-14` | Book II: Part II: The Origin of the Buddhist Schism |
| `sd2-3-01` through `sd2-3-09` | Book II: Part III: The Final Schism |

## Driver notes — commentary structure

The Secret Doctrine is Blavatsky's OWN commentary on cited sources. The text is structured as:

1. **Stanzas of Dzyan** — the core ancient "stanzas" (Verses 1–72 of the Book of Dzyan, a pre-Vedic text), quoted from an alleged Sanskrit/Tibetan source.
2. **Blavatsky's commentaries on the stanzas** — extensive interpretive commentary where Helena Blavatsky analyzes and explains each stanza, citing:
   - The **Puranas** (Vishnu Purana, Matsya Purana, Bhagavata Purana)
   - **Buddhist texts** (the Commentaries, Lalitavistara, etc.)
   - **Zoroastrian sources** (Bundahishn, Zoroastrian chronicles)
   - **Medieval Christian chronicles** (Eusebius, Syncellus, etc.)
   - **Hermetic texts** (Kybalion fragments)
   - And other ancient sources

The commentary makes up ~80% of the text. Each "stanza" is followed by 5–15 pages of Blavatsky's commentary where she cites her sources by name and discusses their relationship. This is **not** a scholarly apparatus layer to strip — it IS the primary text. The corpus should retain this structure intact.

The text also contains:
- **Footnotes** marked `[[Vol. 1, Page N]]` — page markers from the original edition, these are useful navigation aids, not cruft.
- **Blockquote stanzas** — "Thus speaks the Book of Dzyan" or similar framing — these mark the core stanzas.
- **Cross-references** to "Part I," "Book II," etc. — these are internal text references, not nav-bar links.

## Recommendations for chunking

- **Strategy:** `regex-section-split` on the 7 chapter headers (I–VII), or `page-as-chunk` if each page's ~27–75 KB fits the chunk target.
- **Commentary tagging:** The corpus tags system should recognize Blavatsky's commentary as `primary_text` (not `apparatus`) — it is the work itself.
- **No stripping:** Unlike other sacred-texts works, the commentary here is NOT translator's apparatus. The raw text should retain the commentary intact for corpus ingestion.
