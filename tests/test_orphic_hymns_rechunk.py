r"""Regression tests for the Orphic Hymns front-matter drop (todo:df44bdeb).

The Thomas Taylor edition was chunked page-as-chunk, which kept Taylor's
editorial front matter (title page, Preface, "Dissertation on the Life and
Theology of Orpheus") as 34 chunks plus a sacred-texts redirect page. The
re-chunk dropped those 35 chunks (drop_before_marker + drop_chunk_patterns)
and relabelled Hymn XLII, which the source prints as "XLII TO THE SEASONS"
with no period after the numeral.

Three review findings on that change, each pinned here:

1. The relabel fix made `number_pattern` period-optional but left the parallel
   `title_pattern` prefix period-mandatory, so Hymn XLII was labelled "Hymn
   XLII" with no title while every sibling kept one. The\.->\. fix in
   title_pattern recovers "THE SEASONS".
2. `^([IVXLCDM]+)\.?` dropped the guard that separated a Roman-numeral heading
   from an ordinary word of I/V/X/L/C/D/M letters ("CIVIL", "MILD", "DIM").
   The lookahead `(?=\.| TO )` restores the guard: a hymn number is a numeral
   followed by a period or the invocation " TO ".
3. drop_before_marker fails OPEN — a marker that matches nothing keeps
   everything (warning only), so a re-scrape variation silently reintroduces
   the front matter. Assert the emitted corpus actually lost it.

Run with: pytest tests/test_orphic_hymns_rechunk.py
"""

import sys
import tomllib
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "chunking" / "greek_mystery" / "orphic-hymns.toml"
CHUNKS_DIR = PROJECT_ROOT / "corpus" / "greek_mystery" / "orphic-hymns" / "chunks"

sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "chunkers"))
from page_chunker import _extract_number, _extract_title  # noqa: E402


@pytest.fixture(scope="module")
def cfg() -> dict:
    return tomllib.load(open(CONFIG_PATH, "rb"))["chunking"]


# ── finding 2: the numeral guard ────────────────────────────────────────────

def test_number_pattern_rejects_leading_roman_letter_words(cfg):
    r"""A leading word made only of I/V/X/L/C/D/M letters is not a hymn number.
    The optional-period form (`[IVXLCDM]+\.?`) captured "CIVIL"/"MILD"/"DIM";
    the `(?=\.\s*[Tt]|\s*[Tt][Oo] )` lookahead must reject them — including
    when the word is followed by a period ("MILD. air") but not by the hymn
    invocation."""
    for word in ("CIVIL", "MILD", "DIM", "MIXED", "DIVIDED",
                 "MILD. air", "DIM. air", "CIVIL service"):
        assert _extract_number("x", word, cfg) is None, word


def test_number_pattern_accepts_period_and_invocation_forms(cfg):
    """Both the period form ("XLIII. TO SEMELE") and the omitted-period form
    ("XLII TO THE SEASONS") are hymn numbers; mixed-case "To" matches too."""
    assert _extract_number("x", "XLII TO THE SEASONS", cfg) == "XLII"
    assert _extract_number("x", "XLIII. TO SEMELE", cfg) == "XLIII"
    assert _extract_number("x", "XXII. TO NEREUS", cfg) == "XXII"
    assert _extract_number("x", "VI. To the stars", cfg) == "VI"


def test_number_pattern_skips_non_hymn_content(cfg):
    """The dissertation's own opening is not a hymn number."""
    assert _extract_number("x", "A Dissertation ON THE Life and Theology", cfg) is None


# ── finding 1: the XLII title ───────────────────────────────────────────────

def test_title_pattern_recovers_xlii_seasons_title(cfg):
    """Hymn XLII's body starts "XLII TO THE SEASONS." with no period after the
    numeral. The optional-period title prefix must strip the numeral and yield
    "THE SEASONS", matching every sibling hymn's title."""
    xlii_body = tomllib.load(open(CHUNKS_DIR / "042.toml", "rb"))["content"]["body"]
    assert _extract_title(xlii_body, cfg) == "THE SEASONS"


def test_title_pattern_still_extracts_period_form(cfg):
    """The optional-period prefix must not disturb the normal period form."""
    xliii_body = tomllib.load(open(CHUNKS_DIR / "043.toml", "rb"))["content"]["body"]
    assert _extract_title(xliii_body, cfg) == "SEMELE"


# ── finding 3: the emitted corpus lost the front matter ─────────────────────

def test_corpus_has_no_surviving_front_matter():
    """The drop actually happened: no emitted chunk is labelled as front
    matter. Guards the fail-open drop_before_marker — if a re-scrape changed
    the heading and the marker matched nothing, all 34 editorial chunks would
    silently return as "Front Matter, p. N"."""
    offenders = []
    for ct in sorted(CHUNKS_DIR.glob("*.toml")):
        section = tomllib.load(open(ct, "rb"))["chunk"]["section"]
        if section.lower().startswith("front matter"):
            offenders.append(f"{ct.name}: {section!r}")
    assert not offenders, "front-matter chunks survived the drop:\n  " + "\n  ".join(offenders)


def test_corpus_emits_86_hymns_first_to_death():
    """The kept chunks form a complete Hymn I-LXXXVI set with no gaps — the
    front matter (34), redirect (1), and appended editorial sub-splits (17)
    removed from the original 138."""
    labels = [
        tomllib.load(open(ct, "rb"))["chunk"]["section"]
        for ct in sorted(CHUNKS_DIR.glob("*.toml"))
    ]
    assert len(labels) == 86, f"{len(labels)} chunks, expected 86"
    assert labels[0].startswith("Hymn I."), labels[0]
    assert labels[-1].startswith("Hymn LXXXVI."), labels[-1]


def test_no_subsplit_editorial_tails_survive():
    """No chunk may be a pure-commentary sub-split tail (Taylor's appended
    footnotes/essays past the verse). The page's verse always fits in one
    chunk (longest is 567 tokens), so a (part N) chunk whose body does not
    open with a hymn number is editorial overflow, not primary text
    (todo:f1e1e009). Guards drop_trailing_nonprimary_subsplits."""
    import re
    tails = []
    for ct in sorted(CHUNKS_DIR.glob("*.toml")):
        d = tomllib.load(open(ct, "rb"))
        sec, body = d["chunk"]["section"], d["content"]["body"]
        m = re.search(r"\(part (\d+)\)$", sec)
        if m and int(m.group(1)) >= 2:
            tails.append(f"{d['chunk']['id']}: {sec!r}")
    assert not tails, "editorial sub-split tails survived:\n  " + "\n  ".join(tails)


def test_corpus_hymn_xlii_labelled_with_title():
    """Hymn XLII (the chunk that was mislabelled "Front Matter, p. 48") must
    survive as a titled hymn, not an empty-title "Hymn XLII"."""
    label = tomllib.load(open(CHUNKS_DIR / "042.toml", "rb"))["chunk"]["section"]
    assert label == "Hymn XLII. THE SEASONS", label