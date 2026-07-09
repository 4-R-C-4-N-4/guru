"""Invariant tests for the works layer (todo:241430fd, work-grouping.md)."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

import pytest
from works import Work, load_works, work_of, _corpus_texts


@pytest.fixture(scope="module")
def works():
    return load_works()


def test_totals_match_grouping_table(works):
    # work-grouping.md: 52 works — 9 grouped + 43 singleton
    assert len(works) == 52
    grouped = [w for w in works.values() if w.grouped]
    assert len(grouped) == 9
    assert sum(len(w.members) for w in grouped) == 168


def test_every_text_in_exactly_one_work(works):
    texts = _corpus_texts()
    mapping = work_of(works)
    assert set(mapping) == set(texts)          # total coverage, no strays
    assert len(mapping) == 211
    # no double-claims by construction of work_of; assert member disjointness
    all_members = [m for w in works.values() for m in w.members]
    assert len(all_members) == len(set(all_members))


def test_single_tradition_per_work(works):
    texts = _corpus_texts()
    for w in works.values():
        assert {texts[m][0] for m in w.members} == {w.tradition}, w.id


def test_member_reading_order_is_corpus_order(works):
    # Members are shard directories whose natural-sort order IS reading order
    # (verified V2: chunk/file numbering is reading order). Guard the TOML
    # against accidental reorder on edit.
    import re
    nat = lambda s: [int(x) if x.isdigit() else x for x in re.split(r"(\d+)", s)]
    for w in works.values():
        if w.grouped:
            assert list(w.members) == sorted(w.members, key=nat), w.id


def test_known_rows_from_grouping_table(works):
    assert len(works["dhammapada"].members) == 26
    assert len(works["agrippa-natural-magic"].members) == 74
    assert len(works["gathas"].members) == 17
    assert works["gathas"].members[0] == "yasna-28"
    assert works["kalevala"].grouped is False
    assert works["kalevala"].members == ("kalevala",)


def test_validation_rejects_unknown_member(tmp_path):
    bad = tmp_path / "works.toml"
    bad.write_text('[[work]]\nid = "x"\nlabel = "X"\ntradition = "buddhism"\nmembers = ["no-such-text"]\n')
    with pytest.raises(ValueError, match="not in corpus"):
        load_works(bad)


def test_validation_rejects_cross_tradition(tmp_path):
    bad = tmp_path / "works.toml"
    bad.write_text(
        '[[work]]\nid = "x"\nlabel = "X"\ntradition = "buddhism"\n'
        'members = ["diamond-sutra", "kalevala"]\n'
    )
    with pytest.raises(ValueError, match="span traditions"):
        load_works(bad)
