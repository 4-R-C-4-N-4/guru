"""tests/test_taxonomy_structure.py — three-tier taxonomy.toml (todo:a34a9460).

Guards the restructure of concepts/taxonomy.toml into the design.md §6 layout
(domain → family → concept) and the design.md §13 invariant that the
restructure is a no-op for existing readers: both guru.retriever and
scripts.tag_concepts must keep extracting every concept definition regardless
of nesting depth.

Initial state is the single-tier mirror (one family per domain, family id ==
domain id); §4 two-tier clustering is deferred to todo:ea1c2372.
"""
from __future__ import annotations

import importlib.util
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
TAXONOMY = PROJECT_ROOT / "concepts" / "taxonomy.toml"

EXPECTED_DOMAINS = {
    "cosmology", "soteriology", "theology", "praxis", "anthropology", "ethics"
}
TOTAL_CONCEPTS = 88


def _load() -> dict:
    with open(TAXONOMY, "rb") as f:
        return tomllib.load(f)


def _flat_concepts(data: dict) -> dict[str, str]:
    """Collect every leaf {concept_id: definition} under [concepts], any depth."""
    out: dict[str, str] = {}

    def walk(node: dict) -> None:
        for k, v in node.items():
            if isinstance(v, dict):
                walk(v)
            elif isinstance(v, str):
                out[k] = v

    walk(data.get("concepts", {}))
    return out


# ── structure ──────────────────────────────────────────────────────────────


def test_file_parses():
    assert _load()  # tomllib raises on malformed input


def test_domains_present_with_definitions():
    fams = _load()["families"]
    assert EXPECTED_DOMAINS <= set(fams)
    for d in EXPECTED_DOMAINS:
        assert fams[d].get("definition"), f"domain {d} missing definition"


def test_each_domain_has_mirror_family():
    """Initial mirror state: one family per domain, id == domain id, with a
    required gloss (design.md §6 'per-family definition is required')."""
    fams = _load()["families"]
    for d in EXPECTED_DOMAINS:
        assert d in fams[d], f"domain {d} missing its mirror family [{d}.{d}]"
        assert fams[d][d].get("definition"), f"mirror family {d}.{d} missing definition"


def test_concepts_grouped_three_tier():
    """Every concept sits under concepts.DOMAIN.FAMILY (two dotted segments)."""
    concepts = _load()["concepts"]
    assert EXPECTED_DOMAINS <= set(concepts)
    for domain, families in concepts.items():
        for family, members in families.items():
            assert isinstance(members, dict), f"{domain}.{family} not a concept table"
            for cid, defn in members.items():
                assert isinstance(defn, str) and defn, f"{cid} has non-string def"


def test_total_concept_count_preserved():
    assert len(_flat_concepts(_load())) == TOTAL_CONCEPTS


def test_concept_aliases_section_exists():
    # Required by the ticket; empty at migration time (populated incrementally).
    assert "concept_aliases" in _load()


# ── §13 no-op invariant: existing readers tolerate the new nesting ───────────


def test_retriever_loader_reads_all_concepts():
    from guru.retriever import _load_taxonomy_labels

    labels = _load_taxonomy_labels()
    assert len(labels) == TOTAL_CONCEPTS
    assert all(isinstance(v, str) for v in labels.values())


def test_tag_concepts_loader_reads_all_concepts():
    spec = importlib.util.spec_from_file_location(
        "tag_concepts", PROJECT_ROOT / "scripts" / "tag_concepts.py"
    )
    tc = importlib.util.module_from_spec(spec)
    sys.modules["tag_concepts"] = tc
    spec.loader.exec_module(tc)

    concepts = tc.load_taxonomy()
    assert len(concepts) == TOTAL_CONCEPTS
    # load_taxonomy is enriched with family/domain context (todo:17610554, §8).
    expected_keys = {
        "id", "definition", "node_id",
        "family_id", "family_label", "family_definition",
        "domain_id", "domain_label", "domain_definition",
    }
    for c in concepts:
        assert set(c) == expected_keys
        assert c["node_id"] == f"concept.{c['id']}"
        # family_id is the two-segment domain.family path
        assert c["family_id"].startswith(c["domain_id"] + ".")
    # ordered by (domain, family, concept)
    keys = [(c["domain_id"], c["family_id"], c["id"]) for c in concepts]
    assert keys == sorted(keys)


def test_loaders_agree_with_raw_toml():
    """The two loaders and a direct parse must see the same concept set."""
    from guru.retriever import _load_taxonomy_labels

    raw = set(_flat_concepts(_load()))
    assert set(_load_taxonomy_labels()) == raw
