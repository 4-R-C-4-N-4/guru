"""Tests for scripts/backfill_chunk_ids.py (todo:4fd22c34).

Covers normalize_chunk_id (the per-tradition prefix transform) and
rewrite_one (the in-place TOML edit).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from backfill_chunk_ids import TRADITION_MAP, normalize_chunk_id, rewrite_one  # noqa: E402


# ── normalize_chunk_id ────────────────────────────────────────────────


def test_display_name_with_space_normalizes():
    assert normalize_chunk_id("Christian Mysticism.boehme.001") == "christian_mysticism.boehme.001"
    assert normalize_chunk_id("Greek Mystery.orphic-hymns.063") == "greek_mystery.orphic-hymns.063"
    assert normalize_chunk_id("Jewish Mysticism.zohar.012") == "jewish_mysticism.zohar.012"


def test_single_word_capitalized_normalizes():
    assert normalize_chunk_id("Buddhism.diamond-sutra.003") == "buddhism.diamond-sutra.003"
    assert normalize_chunk_id("Neoplatonism.plotinus.500") == "neoplatonism.plotinus.500"
    assert normalize_chunk_id("Egyptian.book-of-the-dead.099") == "egyptian.book-of-the-dead.099"


def test_already_snake_case_returns_none():
    """No rewrite needed — caller treats None as 'leave alone'."""
    assert normalize_chunk_id("gnosticism.gospel-of-thomas.077") is None
    assert normalize_chunk_id("hermeticism.corpus-hermeticum-1.001") is None
    assert normalize_chunk_id("jewish_mysticism.zohar.005") is None


def test_unknown_tradition_returns_none():
    """Don't transform unknown prefixes — could mangle non-chunk IDs."""
    assert normalize_chunk_id("Unknown.text.001") is None
    assert normalize_chunk_id("concept.gnosis_direct_knowledge") is None
    assert normalize_chunk_id("notvalid") is None


def test_partial_match_does_not_normalize():
    """The prefix needs the trailing '.' — substring matches don't count."""
    assert normalize_chunk_id("Buddhismish.text.001") is None


def test_tradition_map_has_no_already_lowercase_keys():
    """Already-snake-case traditions don't belong in the map (would be no-ops
    that confuse the dry-run summary)."""
    for display in TRADITION_MAP:
        assert display != display.lower(), f"{display} is already lowercase"
        assert " " in display or display[0].isupper()


# ── rewrite_one ───────────────────────────────────────────────────────


def _write_chunk(tmp_path: Path, chunk_id: str) -> Path:
    p = tmp_path / "chunk.toml"
    p.write_text(
        f'[chunk]\n'
        f'id = "{chunk_id}"\n'
        f'tradition = "Some Tradition"\n'
        f'text_name = "Foo"\n'
        f'\n[content]\n'
        f'body = "..."\n'
    )
    return p


def test_rewrite_one_swaps_id_and_returns_pair(tmp_path: Path):
    p = _write_chunk(tmp_path, "Christian Mysticism.boehme.001")
    out = rewrite_one(p)
    assert out == ("Christian Mysticism.boehme.001", "christian_mysticism.boehme.001")
    assert 'id = "christian_mysticism.boehme.001"' in p.read_text()


def test_rewrite_one_noop_for_already_snake(tmp_path: Path):
    text_before = _write_chunk(tmp_path, "gnosticism.gospel-of-thomas.077").read_text()
    p = tmp_path / "chunk.toml"
    out = rewrite_one(p)
    assert out is None
    assert p.read_text() == text_before  # bit-identical


def test_rewrite_one_preserves_other_lines(tmp_path: Path):
    """Comments, other keys, formatting must survive untouched."""
    p = tmp_path / "chunk.toml"
    p.write_text(
        '# leading comment\n'
        '[chunk]\n'
        '# inline comment\n'
        'id = "Buddhism.diamond-sutra.003"\n'
        'tradition = "Buddhism"\n'
        '\n'
        '[content]\n'
        'body = "ok"\n'
    )
    rewrite_one(p)
    out = p.read_text()
    assert '# leading comment\n' in out
    assert '# inline comment\n' in out
    assert 'id = "buddhism.diamond-sutra.003"' in out
    assert 'tradition = "Buddhism"' in out  # display name field unchanged
    assert 'body = "ok"' in out


def test_rewrite_one_only_touches_first_id_line(tmp_path: Path):
    """If a body or other section happened to contain 'id = "..."' style text,
    we must not mangle it. Only the first 'id = ' line in the file gets the
    transform."""
    p = tmp_path / "chunk.toml"
    p.write_text(
        '[chunk]\n'
        'id = "Buddhism.diamond-sutra.003"\n'
        '[content]\n'
        'body = "the second id = \\"Buddhism.diamond-sutra.999\\" appears in text"\n'
    )
    rewrite_one(p)
    out = p.read_text()
    assert 'id = "buddhism.diamond-sutra.003"' in out
    # The second occurrence inside body is left intact.
    assert 'Buddhism.diamond-sutra.999' in out
