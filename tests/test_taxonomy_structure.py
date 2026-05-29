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
# 88 original + 7 ex-orphan concepts placed into mirror families (backfill pass).
TOTAL_CONCEPTS = 95


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


def test_clustered_into_real_families():
    """Hand-clustered state (todo:ea1c2372): the §4 two-tier hierarchy — 22
    families across 6 domains, every family with a required gloss, and no
    degenerate mirror family (family id == domain id)."""
    fams = _load()["families"]
    family_ids = [
        f"{d}.{fk}"
        for d in EXPECTED_DOMAINS
        for fk, body in fams[d].items()
        if isinstance(body, dict)
    ]
    assert len(family_ids) == 22, f"expected 22 families, got {len(family_ids)}: {family_ids}"
    # every family has a one-line gloss
    for d in EXPECTED_DOMAINS:
        for fk, body in fams[d].items():
            if isinstance(body, dict):
                assert body.get("definition"), f"family {d}.{fk} missing definition"
    # no mirror families survive (would be id == domain repeated)
    assert not any(fid.split(".")[0] == fid.split(".")[1] for fid in family_ids), \
        "a degenerate mirror family (DOMAIN.DOMAIN) is still present"
    # spot-check a few §4 families landed
    for expected in ("cosmology.divine_structure", "praxis.contemplative_practice",
                     "theology.ontological_structure", "ethics.moral_teaching"):
        d, fk = expected.split(".")
        assert fk in fams[d], f"missing expected family {expected}"


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


def test_concept_aliases_valid():
    """Populated aliases must reference real concepts, be lowercase (the
    concept_aliases.alias CHECK is alias = LOWER(alias)), and never be shared
    across two concepts (which would make a query expand ambiguously)."""
    tax = _load()
    concept_ids = {cid for dom in tax["concepts"].values()
                   for fam in dom.values() for cid in fam}
    aliases = tax["concept_aliases"]
    bad_ids = [k for k in aliases if k not in concept_ids]
    assert not bad_ids, f"alias keys are not real concepts: {bad_ids}"
    not_lower = [(k, a) for k, v in aliases.items() for a in v if a != a.lower()]
    assert not not_lower, f"non-lowercase aliases violate the CHECK: {not_lower}"
    from collections import Counter
    counts = Counter(a for v in aliases.values() for a in v)
    dupes = {a: n for a, n in counts.items() if n > 1}
    assert not dupes, f"aliases shared across concepts (ambiguous expansion): {dupes}"


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
    # Tagging is concept-driven (flat v1 prompt); load_taxonomy returns the bare
    # concept shape, not family-enriched dicts. The grouped v2 prompt was benched
    # and reverted — see docs/concept-hierarchy/bench-v1-vs-v2.md.
    for c in concepts:
        assert set(c) == {"id", "definition", "node_id"}
        assert c["node_id"] == f"concept.{c['id']}"


def test_loaders_agree_with_raw_toml():
    """The two loaders and a direct parse must see the same concept set."""
    from guru.retriever import _load_taxonomy_labels

    raw = set(_flat_concepts(_load()))
    assert set(_load_taxonomy_labels()) == raw
