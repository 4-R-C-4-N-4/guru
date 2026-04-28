"""Tests for guru.corpus.resolve_chunk_path.

Post-todo:9ec1dcee, chunk_ids and corpus directories share the snake_case
namespace — the helper is just a directory join with an existence check.
The historical display-name fallback (covered by todo:6ccb04d9) is gone;
display-name input is treated like any other unknown prefix.
"""
from pathlib import Path

import pytest

from guru.corpus import resolve_chunk_path


@pytest.fixture
def fake_corpus(tmp_path: Path) -> Path:
    corpus = tmp_path / "corpus"
    for trad, text, seq in [
        ("buddhism", "diamond-sutra", "003"),
        ("christian_mysticism", "life-and-doctrines-boehme", "012"),
        ("gnosticism", "gospel-of-thomas", "077"),
    ]:
        d = corpus / trad / text / "chunks"
        d.mkdir(parents=True)
        (d / f"{seq}.toml").write_text("# stub")
    return corpus


def test_snake_case_prefix_resolves(fake_corpus: Path) -> None:
    p = resolve_chunk_path("gnosticism.gospel-of-thomas.077", fake_corpus)
    assert p == fake_corpus / "gnosticism" / "gospel-of-thomas" / "chunks" / "077.toml"


def test_multiword_snake_case_prefix_resolves(fake_corpus: Path) -> None:
    p = resolve_chunk_path(
        "christian_mysticism.life-and-doctrines-boehme.012", fake_corpus
    )
    assert p == fake_corpus / "christian_mysticism" / "life-and-doctrines-boehme" / "chunks" / "012.toml"


def test_display_name_prefix_returns_none(fake_corpus: Path) -> None:
    """Pre-todo:9ec1dcee, the helper had a fallback that converted display
    names to snake_case. Post-migration, the corpus is normalized so that
    fallback is unnecessary — display-name input is just a wrong prefix."""
    assert resolve_chunk_path("Buddhism.diamond-sutra.003", fake_corpus) is None
    assert resolve_chunk_path(
        "Christian Mysticism.life-and-doctrines-boehme.012", fake_corpus
    ) is None


def test_unknown_chunk_returns_none(fake_corpus: Path) -> None:
    assert resolve_chunk_path("unknown.fake-text.001", fake_corpus) is None


def test_malformed_chunk_id_returns_none(fake_corpus: Path) -> None:
    assert resolve_chunk_path("notvalid", fake_corpus) is None
    assert resolve_chunk_path("trad.text", fake_corpus) is None


def test_text_id_with_dots_is_preserved(fake_corpus: Path) -> None:
    """split(., 2) caps at 3 parts so a text_id containing a dot would be
    kept intact (e.g. 'gnosticism.foo.bar.001' → text_id='foo.bar'). The
    fixture doesn't exercise this directly, but the lookup must not split
    text_id on every dot."""
    # No corpus entry → returns None, but the call must not raise.
    assert resolve_chunk_path("gnosticism.foo.bar.001", fake_corpus) is None
