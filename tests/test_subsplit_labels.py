"""
Sub-chunk label suffixes must stay alphabetic (todo:f39248b9).

The old suffix generator was chr(ord('a') + idx): fine through 'z', then it
walked into ASCII punctuation for any section with >26 sub-chunks — Secret
Teachings shipped "…Symbolism{" / "…Symbolism|" / "…Symbolism~" into corpus
section labels, and guru-web renders those in headings and <title> tags.

1. _letter_suffix is bijective base-26 (a..z, aa, ab, …).
2. subsplit emits alphabetic suffixes past the 26th sub-chunk.
3. Corpus guard: no stored section label ends in the overflow junk range.

Run with: pytest tests/test_subsplit_labels.py
"""

import re
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
CORPUS_DIR = PROJECT_ROOT / "corpus"

sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "chunkers"))
from regex_splitter import Chunk, _letter_suffix, subsplit  # noqa: E402


def test_letter_suffix_first_26_unchanged():
    assert [_letter_suffix(i) for i in range(26)] == [chr(ord("a") + i) for i in range(26)]


def test_letter_suffix_rolls_to_double_letters_past_z():
    assert _letter_suffix(26) == "aa"
    assert _letter_suffix(27) == "ab"
    assert _letter_suffix(51) == "az"
    assert _letter_suffix(52) == "ba"
    assert _letter_suffix(701) == "zz"
    assert _letter_suffix(702) == "aaa"


def test_letter_suffix_always_alphabetic():
    assert all(_letter_suffix(i).isalpha() for i in range(1000))


def test_subsplit_labels_stay_alphabetic_past_26_parts():
    # 30 paragraphs, each over the token budget on its own, forces 30 flushes.
    body = "\n\n".join(f"paragraph {i} " + "word " * 40 for i in range(30))
    subs = subsplit(Chunk(section_label="Symbolism", body=body), max_tokens=30,
                    count_fn=lambda t: len(t.split()))
    assert len(subs) > 26
    labels = [s.section_label for s in subs]
    assert labels[:2] == ["Symbolisma", "Symbolismb"]
    assert labels[26] == "Symbolismaa"
    for label in labels:
        suffix = label[len("Symbolism"):]
        assert suffix.isalpha(), f"non-alphabetic suffix in {label!r}"


def test_corpus_has_no_overflow_suffix_labels():
    """Guard on the stored corpus: the ASCII range just past 'z' ({|}~ and
    the [\\]^_` block just past 'Z') can only come from the overflow bug —
    no legitimate section label ends with those."""
    junk_tail = re.compile(r'[{|}~\[\]^_`\\]$')
    bad = []
    for path in CORPUS_DIR.glob("*/*/chunks/*.toml"):
        with open(path, "rb") as f:
            section = tomllib.load(f)["chunk"]["section"]
        if junk_tail.search(section):
            bad.append(f"{path}: {section!r}")
    assert not bad, "overflowed sub-chunk labels in corpus:\n" + "\n".join(bad[:20])
