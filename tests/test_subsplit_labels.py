"""
Sub-chunk label suffixes must stay alphabetic (todo:f39248b9).

The old suffix generator was chr(ord('a') + idx): fine through 'z', then it
walked into ASCII punctuation for any section with >26 sub-chunks — Secret
Teachings shipped "…Symbolism{" / "…Symbolism|" / "…Symbolism~" into corpus
section labels, and guru-web renders those in headings and <title> tags.
Past the 30th sub-chunk it went further still: DEL (\\x7f) and invisible C1
control characters (Divine Names ch.4 reached \\x87).

1. _letter_suffix is bijective base-26 (a..z, aa, ab, …).
2. subsplit emits alphabetic suffixes past the 26th sub-chunk.
3. Corpus guard: no stored section label ends in the overflow junk range,
   and the junk pattern provably covers the old generator's full output.

The suffix is also separated from the label (todo:0888eb07). Appended bare it
fused into the last word — "Preface" -> "Prefacea", "Rune XXXVIII" ->
"Rune XXXVIIIa" — and `section` is what a citation renders, so those are
reader-facing strings. Roman numerals were the worst case: "Chapter VIa" is
ambiguous between VI + "a" and V + "ia".

4. subsplit puts SUB_SEP between label and suffix.
5. Corpus guard: no stored label fuses a suffix run onto a letter-ending stem.

Run with: pytest tests/test_subsplit_labels.py
"""

import re
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_DIR = PROJECT_ROOT / "corpus"

sys.path.insert(0, str(PROJECT_ROOT / "scripts" / "chunkers"))
from regex_splitter import SUB_SEP, Chunk, _letter_suffix, subsplit  # noqa: E402

# Everything the old chr-based generator emitted past 'z': ASCII punctuation
# {|}~, then DEL and the C1 controls (idx 26..62). Plus the [\]^_` block just
# past 'Z' in case an upper-cased variant ever existed. No legitimate section
# label ends with any of these.
JUNK_TAIL = re.compile(r'[{|}~\[\]^_`\\\x7f-\x9f]$')


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


def _split_30(label="Symbolism"):
    # 30 paragraphs, each over the token budget on its own, forces 30 flushes.
    body = "\n\n".join(f"paragraph {i} " + "word " * 40 for i in range(30))
    return subsplit(Chunk(section_label=label, body=body), max_tokens=30,
                    count_fn=lambda t: len(t.split()))


def test_subsplit_labels_stay_alphabetic_past_26_parts():
    subs = _split_30()
    assert len(subs) > 26
    labels = [s.section_label for s in subs]
    assert labels[:2] == [f"Symbolism{SUB_SEP}a", f"Symbolism{SUB_SEP}b"]
    assert labels[26] == f"Symbolism{SUB_SEP}aa"
    for label in labels:
        suffix = label[len("Symbolism") + len(SUB_SEP):]
        assert suffix.isalpha(), f"non-alphabetic suffix in {label!r}"


def test_subsplit_separates_suffix_from_a_letter_ending_label():
    """The todo:0888eb07 cases: bare append fused the suffix into the word."""
    for label, first in [("Preface", "Preface-a"),
                         ("The Monad", "The Monad-a"),
                         ("Chapter VI", "Chapter VI-a"),
                         ("Rune XXXVIII", "Rune XXXVIII-a"),
                         ("Document FIRST", "Document FIRST-a")]:
        subs = _split_30(label)
        assert subs[0].section_label == first
        # The label survives intact — a reader can still recover the section
        # it came from by cutting at the last separator.
        assert subs[5].section_label.rsplit(SUB_SEP, 1)[0] == label


def test_subsplit_separator_applies_to_digit_ending_labels_too():
    """No special case: "Section 1a" read fine, but one convention beats two."""
    assert _split_30("Section 1")[0].section_label == "Section 1-a"


def test_label_is_recoverable_from_a_suffixed_label():
    """rsplit on the separator is the inverse. Only holds because the suffix
    is [a-z]+ and the separator is the last one in the string — a label that
    itself contains SUB_SEP ("Chapter 4, Section 1-2") still cuts correctly."""
    subs = _split_30("Chapter 4, Section 1-2")
    for s in subs:
        stem, suffix = s.section_label.rsplit(SUB_SEP, 1)
        assert stem == "Chapter 4, Section 1-2"
        assert suffix.isalpha()


def test_junk_tail_covers_old_generator_output():
    """The guard must catch every suffix the old generator could emit past
    'z' — including DEL and the invisible C1 controls that Divine Names ch.4
    actually shipped (idx 30..38), which punctuation-only matching missed.
    idx 62 (\\x9f) is the last C1 control; no section ever came close."""
    for idx in range(26, 63):
        old_suffix = chr(ord("a") + idx)
        assert JUNK_TAIL.search(f"Symbolism{old_suffix}"), \
            f"guard misses old-generator suffix {old_suffix!r} (idx {idx})"


def test_new_suffixes_never_trip_the_guard():
    assert not any(JUNK_TAIL.search(f"Symbolism{_letter_suffix(i)}") for i in range(1000))


def _suffix_runs(labels: list[str]) -> list[tuple[str, int]]:
    """Consecutive labels forming STEM+a, STEM+b, … — i.e. one subsplit call's
    output. Detecting the run rather than pattern-matching a single label is
    what keeps prose section names out of the result: "The Savior Appears"
    ends in [a-z]+ but nothing follows it ending in 'b' on the same stem."""
    runs, i = [], 0
    while i < len(labels):
        if labels[i].endswith("a"):
            stem = labels[i][:-1]
            n = 1
            while i + n < len(labels) and labels[i + n] == stem + _letter_suffix(n):
                n += 1
            if n >= 2:
                runs.append((stem, n))
                i += n
                continue
        i += 1
    return runs


# apocryphon-of-john cannot be re-chunked from this checkout: its raw is
# produced by scripts/pdf_synoptic_extract.py from a local PDF that is not in
# the repository, and raw/ is git-ignored. Its 9 fused labels clear the next
# time someone with the PDF re-runs node 05. Tracked on todo:0888eb07.
FUSED_BLOCKED_ON_RAW = {"apocryphon-of-john"}


def test_corpus_has_no_fused_sub_chunk_labels():
    """Guard on the stored corpus for todo:0888eb07: no suffix run sits
    directly against a stem ending in a letter. 14 texts / 1,752 chunks were
    re-chunked to clear this; a new one can only come from a chunker that
    dropped the separator."""
    fused = []
    for text_dir in sorted(CORPUS_DIR.glob("*/*/chunks")):
        text_id = text_dir.parts[-2]
        if text_id in FUSED_BLOCKED_ON_RAW:
            continue
        labels = []
        for path in sorted(text_dir.glob("*.toml")):
            with open(path, "rb") as f:
                labels.append(tomllib.load(f)["chunk"]["section"])
        for stem, n in _suffix_runs(labels):
            if re.search(r"[A-Za-z]$", stem):
                fused.append(f"{text_id}: {stem!r} x{n}")
    assert not fused, ("sub-chunk suffixes fused onto the label:\n"
                       + "\n".join(fused[:20]))


def test_fused_allowlist_stays_earned():
    """An allowlisted text must still be genuinely un-chunkable. When the raw
    reappears, this fails and the entry comes out — the allowlist cannot
    quietly outlive its reason.

    The glob is `{text_id}*.txt`, not `{text_id}.txt`, because that is not the
    name the raw arrives under. `pdf_synoptic_extract.py:410` writes
    `apocryphon-of-john-{codex-ii,bg-8502,codex-iii}.txt` and the manifest's
    documented command produces exactly those; `chunk.py:269` wants
    `apocryphon-of-john.txt`, so there is a rename in between. Watching only
    the post-rename name means the canary stays green through the window where
    the raw is present and the text is chunkable.

    Machine-dependent by construction: `raw/` is git-ignored, so this can never
    fire in CI, and it *will* fail on a checkout that legitimately holds the
    raw. That failure is the message — regenerate the corpus and delete the
    allowlist entry.
    """
    for text_id in FUSED_BLOCKED_ON_RAW:
        raws = sorted((PROJECT_ROOT / "raw").glob(f"*/{text_id}*.txt"))
        assert not raws, (
            f"{text_id} has raw again ({', '.join(p.name for p in raws)}) — "
            f"rename to {text_id}.txt if needed, re-chunk, and drop it from "
            f"FUSED_BLOCKED_ON_RAW")


def test_corpus_has_no_overflow_suffix_labels():
    """Guard on the stored corpus: no section label ends in the overflow
    junk range. Can only come from the suffix bug — see JUNK_TAIL."""
    bad = []
    for path in CORPUS_DIR.glob("*/*/chunks/*.toml"):
        with open(path, "rb") as f:
            section = tomllib.load(f)["chunk"]["section"]
        if JUNK_TAIL.search(section):
            bad.append(f"{path}: {section!r}")
    assert not bad, "overflowed sub-chunk labels in corpus:\n" + "\n".join(bad[:20])
