"""Tests for scripts/audit_readability.py (todo:82e3a09d).

Synthetic bodies exercise each damage signal in isolation; clean prose must
score near zero so the ranking separates damaged texts instead of flagging
everything. The scanner is read-only, so no DB fixture is needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from audit_readability import score_body  # noqa: E402


CLEAN_PROSE = (
    "The One is beyond being, and naming fails it. Whatever we say of it, "
    "we say of something else; it remains prior to every predicate.\n\n"
    "Therefore the soul ascends not by adding knowledge but by letting go, "
    "until nothing remains between the seer and the seen."
)


def test_clean_prose_scores_near_zero():
    s = score_body(CLEAN_PROSE)
    assert s["score"] < 5.0
    assert s["hard_wrap"] == 0.0
    assert s["page_marks"] == 0.0


def test_hard_wrapped_prose_fires_hard_wrap():
    body = (
        "the god Ra rose from the\n"
        "waters of Nun and spoke the\n"
        "names of all living things and\n"
        "they came into being upon the\n"
        "earth and in the sky above"
    )
    s = score_body(body)
    assert s["hard_wrap"] > 0.5
    assert s["score"] > 15.0


def test_hyphen_break_detected_separately_from_wrap():
    body = "the temple of the ever-\nlasting horizon stood in splen-\ndour upon the plain"
    s = score_body(body)
    assert s["hyphen_break"] > 0.0
    assert s["hard_wrap"] == 0.0


def test_caps_header_lines():
    body = "THE BOOK OF THE DEAD\n\nTHE CHAPTER OF COMING FORTH BY DAY\n\nOsiris speaks in the hall."
    s = score_body(body)
    assert s["caps_runs"] > 0.0


def test_page_marks_and_bare_number_lines():
    body = "and the scribe Ani says [p. 143] that the heart\n27\nshall be weighed. [Pg 12]"
    s = score_body(body)
    assert s["page_marks"] > 0.0


def test_footnote_markers():
    body = "As the master said [1], the way that can be told {2} is not the way ^3."
    s = score_body(body)
    assert s["footnotes"] > 0.0


def test_bracket_and_ellipsis_noise():
    body = "the god [...] spoke [sic] unto the (?) assembly [...] and was silent"
    s = score_body(body)
    assert s["brackets"] > 0.0


def test_dot_leaders():
    body = "Chapter the First .......... 12\nChapter the Second .......... 34"
    s = score_body(body)
    assert s["dot_leaders"] > 0.0


def test_signals_are_bounded_zero_to_one():
    nasty = ("[p. 1] " + "A\n" * 50 + "[...]" * 200 + "." * 400 + "\n\n\n\n\n\n" + "x  y " * 100) * 5
    s = score_body(nasty)
    for k, v in s.items():
        if k == "score":
            assert 0.0 <= v <= 100.0
        else:
            assert 0.0 <= v <= 1.0, f"{k} out of bounds: {v}"


def test_empty_body_scores_zero():
    s = score_body("")
    assert s["score"] == 0.0
