#!/usr/bin/env python3
"""Reformat Zinner/Mattison's synoptic 'Secret Writing According to John' PDF.

The PDF sets four witnesses to the Apocryphon of John in three columns:

    Codex II, 1 (with Codex IV, 1 readings in italics) | BG 8502 | Codex III, 1

Columns are positionally clean (col origins 36.6 / 215.2 / 393.6 pt) and
parallel paragraph groups start at the *same* y in every column, so both the
per-witness reconstruction and the synoptic alignment are exact rather than
heuristic.

Line-level markup recovered from font runs:
    Garamond-Italic 11  -> Codex IV, 1 parallel reading   -> *italic*
    BerlinSans 11       -> Coptic codex page number       -> [II, 2] / [19]
    Garamond 7          -> footnote reference             -> [^n]
    BerlinSans 12       -> section heading (page-centred) -> == Heading ==
    Garamond <=10       -> footnote body / page number    -> collected / dropped

Requires PyMuPDF (`pip install pymupdf`), which is not otherwise a dependency
of this repo. Usage:

    python3 scripts/pdf_synoptic_extract.py <pdf> -o raw/gnosticism/

Indent offset from the column origin encodes structure:
    ~0    flush left        -> continuation of a prose paragraph
    ~8    verse line start  -> new colometric line
    ~13   prose indent      -> new prose paragraph
    >=15  hanging indent    -> continuation of the previous verse line
"""

import argparse
import re
import sys
from pathlib import Path

import pymupdf

COL_ORIGINS = {1: 36.6, 2: 215.2, 3: 393.6}
COL_SPLITS = (212.0, 390.0)          # x0 thresholds between columns
BODY_SIZE_MIN = 10.6                 # body text is 11pt; apparatus is <=10pt
PAGE_CENTER = (288.0, 324.0)         # x-centre band for page-wide headings
FRONT_MATTER_Y = 455.0               # on page 1, everything above this is apparatus
RUNNING_HEADERS = {
    "Codex II, 1 (italics = IV, 1)",
    "BG 8502",
    "Codex III, 1",
}
WITNESSES = {
    1: ("codex-ii", "Codex II, 1 (italics = Codex IV, 1)"),
    2: ("bg-8502", "Berlin Codex (BG 8502, 2)"),
    3: ("codex-iii", "Codex III, 1"),
}


def column_of(x0: float) -> int:
    return 1 if x0 < COL_SPLITS[0] else (2 if x0 < COL_SPLITS[1] else 3)


def span_style(span: dict) -> str:
    font, size = span["font"], span["size"]
    if size < 8.0:
        return "ref"                                     # superscript note ref
    if font.startswith("BerlinSans"):
        # 11pt bold runs are Coptic codex page numbers set inside the text;
        # 12pt+ bold is a heading or a running column header.
        return "marker" if size < 11.5 else "display"
    return "italic" if "Italic" in font else "body"


def render_line(line: dict) -> str:
    """Flatten a line's spans, converting font runs into inline markup.

    Adjacent same-style spans are merged first: a single codex marker is often
    split across spans ("IV," + " 11"), which would otherwise render as two
    separate brackets.
    """
    # A wholly-bold line is a heading or an editorial note, not an inline
    # codex page number, so its brackets must not be added.
    plain_bold = all(s["font"].startswith("BerlinSans")
                     for s in line["spans"] if s["text"].strip())
    runs: list[list] = []
    for span in line["spans"]:
        if not span["text"]:
            continue
        style = span_style(span)
        if runs and runs[-1][0] == style:
            runs[-1][1] += span["text"]
        else:
            runs.append([style, span["text"]])

    out = []
    for style, text in runs:
        stripped = text.strip()
        if style == "ref":
            if stripped:
                out.append(f"[^{stripped}]")
        elif style == "marker":
            if not stripped:
                out.append(" ")
            elif plain_bold:
                out.append(text)
            else:
                # MARK, not "[...]": a printed bracketed number in the source
                # ("the other [3]60 angels", a restored digit) is indistinguish-
                # able from a codex page marker once both are brackets, and the
                # qualifier below would rewrite it into "[III, 3]60".
                out.append(f" {MARK}{stripped}{MARK} ")
        elif style == "italic":
            if stripped:
                lead = " " if text[:1].isspace() else ""
                trail = " " if text[-1:].isspace() else ""
                out.append(f"{lead}*{stripped}*{trail}")
            else:
                out.append(text)
        else:
            out.append(text)
    return re.sub(r"\s+", " ", "".join(out)).strip()


def tidy(text: str) -> str:
    # A codex page marker split across a line break ("IV," / "10") renders as
    # two brackets; rejoin them.
    text = re.sub(r"\[([^\[\]]{1,8},)\]\s*\[(\d+)\]", r"[\1 \2]", text)
    # Protect the printed lacuna ellipsis "[. . .]" from the
    # space-before-punctuation cleanup below, which would collapse it.
    text = text.replace("[. . .]", "\x00")
    text = re.sub(r"\s+([,.;:?!’”])", r"\1", text)
    text = text.replace("\x00", "[. . .]")
    text = re.sub(r"\*\s+\*", " ", text)                 # merged italic runs
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


# Bare bracketed numbers collide with the corpus-wide P9 footnote-reference
# strip in clean_bodies.py (r"\s*\[\d{1,3}\]"), which would silently eat the
# Coptic page numbers and leave an orphaned "[II,]" behind. Every marker
# therefore carries its witness.
MARK = "\x01"          # delimits a bold codex page marker until it is qualified
SEP = "\x02"           # paragraph joiner while repairing a column
DEFAULT_PREFIX = {1: "II, ", 2: "BG ", 3: "III, "}


def repair_column(paras: list, col: int) -> None:
    """Qualify each witness's page markers, then set ``rendered`` on each para.

    Runs over a whole column at once because a marker set across a line *or a
    paragraph* break arrives as two pieces ("[IV,]" then "[44]"), and because
    the Codex II stream alternates between II and IV markers — so a bare number
    takes the most recent witness seen, not a fixed default.
    """
    blob = SEP.join(p.text() for p in paras)
    def rejoin(m):
        # Any paragraph separators swallowed by the match are re-emitted, so
        # the blob still splits back into exactly len(paras) pieces.
        return f"{MARK}{m.group(1)} {m.group(2)}{MARK}" + SEP * m.group(0).count(SEP)

    blob = re.sub(rf"{MARK}([^{MARK}]{{1,8}},){MARK}[\s{SEP}]*{MARK}(\d+){MARK}",
                  rejoin, blob)

    last = DEFAULT_PREFIX[col]

    def qualify(m):
        nonlocal last
        inner = m.group(1).strip()
        if inner.isdigit():
            return f"[{last}{inner}]"
        prefix = re.match(r"([A-Za-z]{1,4},?\s*)", inner)
        if prefix:
            last = prefix.group(1).rstrip() + " "
        return f"[{inner}]"

    blob = re.sub(rf"{MARK}([^{MARK}]*){MARK}", qualify, blob)
    for para, text in zip(paras, blob.split(SEP)):
        para.rendered = re.sub(r"\s{2,}", " ", text).strip()


class Paragraph:
    """One paragraph group of one witness, with the y it is aligned on."""

    def __init__(self, page: int, y: float, col: int, kind: str):
        self.page, self.y, self.col, self.kind = page, y, col, kind
        self.lines: list[str] = []
        self.rendered = ""          # set by repair_column()

    def text(self) -> str:
        return "\n".join(tidy(l) for l in self.lines if tidy(l))


def parse(pdf_path: Path):
    doc = pymupdf.open(pdf_path)
    front: list[str] = []
    paragraphs: list[Paragraph] = []          # in document order
    headings: list[tuple[int, float, str]] = []   # (page, y, text)
    footnotes: dict[str, str] = {}
    unplaced: list[str] = []

    for pno in range(doc.page_count):
        page_lines = []
        note_lines = []
        for block in doc[pno].get_text("dict")["blocks"]:
            if block["type"] != 0:
                continue
            for line in block["lines"]:
                raw = "".join(s["text"] for s in line["spans"])
                size = max((s["size"] for s in line["spans"] if s["text"].strip()),
                           default=0.0)
                x0, y0, x1, _ = line["bbox"]
                if not raw.strip():
                    page_lines.append((y0, x0, x1, None, size))   # spacer
                    continue
                if size < BODY_SIZE_MIN:
                    if y0 > 725 and raw.strip().isdigit():        # page number
                        continue
                    note_lines.append((y0, x0, line))
                    continue
                page_lines.append((y0, x0, x1, line, size))

        if pno == 0:
            # Page 1 carries the title, licence and symbol key above the first
            # set of column headers (y=464); the Prologue starts below them.
            kept = []
            for entry in sorted(page_lines):
                y0, x0, x1, line, size = entry
                if y0 > FRONT_MATTER_Y:
                    kept.append(entry)
                    continue
                if line is None:
                    continue
                txt = tidy(render_line(line))
                if txt and txt not in RUNNING_HEADERS:
                    front.append(txt)
            page_lines = kept

        # --- footnotes: a 6.5pt marker opens one, 10pt lines continue it -----
        current = None
        for y0, x0, line in sorted(note_lines):
            rendered = tidy(render_line(line))
            opener = re.match(r"^\[\^([^\]]+)\]\s*", rendered)
            marker = opener.group(1) if opener else None
            body = rendered[opener.end():] if opener else rendered
            if marker:
                current = marker
                footnotes[current] = body
            elif current:
                footnotes[current] = tidy(footnotes[current] + " " + body)
            elif body:
                unplaced.append(body)

        # --- page-wide section headings -------------------------------------
        body_lines = []
        for y0, x0, x1, line, size in sorted(page_lines):
            if line is None:
                body_lines.append((y0, x0, None))
                continue
            txt = tidy(render_line(line))
            if not txt:
                body_lines.append((y0, x0, None))
                continue
            bold = all(s["font"].startswith("BerlinSans")
                       for s in line["spans"] if s["text"].strip())
            if bold and txt in RUNNING_HEADERS:
                continue
            if bold and size >= 11.5 and PAGE_CENTER[0] <= (x0 + x1) / 2 <= PAGE_CENTER[1]:
                headings.append((pno + 1, y0, txt))
                continue
            body_lines.append((y0, x0, txt))

        # --- per-column paragraph assembly ----------------------------------
        for col in (1, 2, 3):
            origin = COL_ORIGINS[col]
            open_para: Paragraph | None = None
            pending_break = False
            for y0, x0, txt in body_lines:
                if column_of(x0) != col:
                    continue
                if txt is None:
                    if open_para is not None:
                        pending_break = True
                    continue
                offset = x0 - origin
                if pending_break:
                    open_para, pending_break = None, False
                if offset < 4.0:                       # flush -> prose runs on
                    kind = "prose"
                    if open_para is None:
                        open_para = Paragraph(pno + 1, y0, col, kind)
                        paragraphs.append(open_para)
                        open_para.lines.append(txt)
                    else:
                        open_para.lines[-1] += " " + txt
                elif offset < 11.0:                    # verse line
                    if open_para is None or open_para.kind != "verse":
                        open_para = Paragraph(pno + 1, y0, col, "verse")
                        paragraphs.append(open_para)
                    open_para.lines.append(txt)
                elif offset < 15.0:                    # new prose paragraph
                    open_para = Paragraph(pno + 1, y0, col, "prose")
                    paragraphs.append(open_para)
                    open_para.lines.append(txt)
                else:                                  # hanging continuation
                    if open_para is None:
                        open_para = Paragraph(pno + 1, y0, col, "verse")
                        paragraphs.append(open_para)
                        open_para.lines.append(txt)
                    else:
                        open_para.lines[-1] += " " + txt

    return front, paragraphs, headings, footnotes, unplaced


def build_stream(paragraphs, headings, col):
    """Interleave one witness's paragraphs with the shared section headings."""
    items = [(p.page, p.y, "para", p) for p in paragraphs if p.col == col]
    items += [(pg, y, "head", txt) for pg, y, txt in headings]
    items.sort(key=lambda i: (i[0], i[1]))
    return items


def witness_text(paragraphs, headings, col, front_title):
    out = [front_title, ""]
    for _, _, kind, payload in build_stream(paragraphs, headings, col):
        if kind == "head":
            out += ["", f"== {payload} ==", ""]
        else:
            body = payload.rendered
            if body:
                out += [body, ""]
    text = "\n".join(out)
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def synoptic_md(front, paragraphs, headings, footnotes):
    # Parallel groups are set at the same y, but a witness may break a group
    # into two paragraphs where another keeps it whole, so exact y-matching
    # fragments the table. Instead sweep paragraphs in reading order and close
    # the current row as soon as a column would be filled twice.
    rows: list[tuple[int, float, dict]] = []
    current: dict = {}
    for p in sorted(paragraphs, key=lambda p: (p.page, p.y, p.col)):
        if not p.rendered:
            continue
        if p.col in current:
            current = {}
        if not current:
            rows.append((p.page, p.y, current))
        current[p.col] = p
    keyed = [(pg, y, "row", cols) for pg, y, cols in rows if cols]
    keyed += [(pg, y, "head", txt) for pg, y, txt in headings]
    keyed.sort(key=lambda i: (i[0], i[1]))

    out = ["# The Secret Writing According to John", "",
           "*A Public Domain Synoptic Translation — NHC II,1 // NHC IV,1 // "
           "BG 8502 // NHC III,1*", "",
           "Translated by Samuel Zinner, edited by Mark M. Mattison. "
           "Committed to the public domain.", "",
           "Italics in the Codex II column are readings from Codex IV, 1. "
           "`[II, 2]`, `[19]`, `[3]` are Coptic codex page numbers; `[. . .]` "
           "and `[ ]` mark lacunae; `( )` editorial insertions; `< >` "
           "editorial corrections; `{ }` scribal errors.", "", "---", ""]
    for _, _, kind, payload in keyed:
        if kind == "head":
            out += [f"## {payload}", ""]
            continue
        for col in (1, 2, 3):
            para = payload.get(col)
            if para is None or not para.rendered:
                continue
            out += [f"**{WITNESSES[col][1]}**", "",
                    "\n".join("> " + l for l in para.rendered.split("\n")), ""]
        out += ["---", ""]
    if footnotes:
        out += ["## Translator's notes", ""]
        for n in sorted(footnotes, key=lambda k: int(k) if k.isdigit() else 0):
            out.append(f"{n}. {footnotes[n]}")
        out.append("")
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("-o", "--outdir", required=True)
    args = ap.parse_args()

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    front, paragraphs, headings, footnotes, unplaced = parse(Path(args.pdf))
    for col in WITNESSES:
        repair_column([p for p in paragraphs if p.col == col], col)
    footnotes = {k: re.sub(rf"{MARK}([^{MARK}]*){MARK}", r"[\1]", v).strip()
                 for k, v in footnotes.items()}

    note_block = ""
    if footnotes:
        note_block = "\n\n== Translator's notes ==\n\n" + "\n".join(
            f"[^{n}] {footnotes[n]}"
            for n in sorted(footnotes, key=lambda k: int(k) if k.isdigit() else 0)
        ) + "\n"

    for col, (slug, label) in WITNESSES.items():
        header = (
            "The Secret Writing According to John (Apocryphon of John)\n"
            f"Witness: {label}\n"
            "Translated by Samuel Zinner, edited by Mark M. Mattison. "
            "Public domain.\n"
            "Source: A Public Domain Synoptic Translation, "
            "https://othergospels.com/john\n"
        )
        path = outdir / f"apocryphon-of-john-{slug}.txt"
        path.write_text(witness_text(paragraphs, headings, col, header)
                        + note_block, encoding="utf-8")
        print(f"wrote {path}")

    (outdir / "apocryphon-of-john-synoptic.md").write_text(
        synoptic_md(front, paragraphs, headings, footnotes), encoding="utf-8")
    print(f"wrote {outdir / 'apocryphon-of-john-synoptic.md'}")
    (outdir / "front-matter.txt").write_text("\n".join(front) + "\n",
                                             encoding="utf-8")

    print(f"\nparagraphs: {len(paragraphs)}  headings: {len(headings)}  "
          f"footnotes: {len(footnotes)}", file=sys.stderr)
    if unplaced:
        print(f"WARNING: {len(unplaced)} unplaced apparatus lines", file=sys.stderr)
        for u in unplaced[:5]:
            print("  ", u[:90], file=sys.stderr)


if __name__ == "__main__":
    main()
