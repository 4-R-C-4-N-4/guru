"""Regression test for chunk-id -> corpus-path resolution (todo:6ccb04d9).

Tradition prefixes in chunk_ids carry display names ("Christian Mysticism")
while directories are snake_case ("christian_mysticism"). The helper must
resolve both forms, otherwise ~90% of staged_tags rows render with empty body
in the review CLIs.
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


def test_display_name_prefix_resolves_to_snake_case_dir(fake_corpus: Path) -> None:
    p = resolve_chunk_path("Buddhism.diamond-sutra.003", fake_corpus)
    assert p == fake_corpus / "buddhism" / "diamond-sutra" / "chunks" / "003.toml"


def test_multiword_display_name_prefix_resolves(fake_corpus: Path) -> None:
    p = resolve_chunk_path(
        "Christian Mysticism.life-and-doctrines-boehme.012", fake_corpus
    )
    assert p == fake_corpus / "christian_mysticism" / "life-and-doctrines-boehme" / "chunks" / "012.toml"


def test_already_snake_case_prefix_resolves(fake_corpus: Path) -> None:
    p = resolve_chunk_path("gnosticism.gospel-of-thomas.077", fake_corpus)
    assert p == fake_corpus / "gnosticism" / "gospel-of-thomas" / "chunks" / "077.toml"


def test_unknown_chunk_returns_none(fake_corpus: Path) -> None:
    assert resolve_chunk_path("Unknown.fake-text.001", fake_corpus) is None


def test_malformed_chunk_id_returns_none(fake_corpus: Path) -> None:
    assert resolve_chunk_path("notvalid", fake_corpus) is None
    assert resolve_chunk_path("trad.text", fake_corpus) is None
