"""tests/test_tag_prompt_hierarchy.py — v2 grouped tagger prompt (todo:17610554).

Covers the design.md §8 prompt change: load_taxonomy() enriches each concept
with family/domain context, build_prompt() renders concepts grouped by
domain → family with one-line glosses, and PROMPT_VERSION bumps to v2. The
JSON *output* contract is unchanged.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from tag_concepts import build_prompt, load_taxonomy  # noqa: E402
from guru.prompt import PROMPT_VERSION  # noqa: E402


ENRICHED = [
    {
        "id": "monad", "definition": "The absolutely simple first principle.",
        "node_id": "concept.monad",
        "family_id": "cosmology.divine_structure",
        "family_label": "Divine Structure",
        "family_definition": "The architecture of the highest realms.",
        "domain_id": "cosmology", "domain_label": "Cosmology",
        "domain_definition": "Origin and structure of the universe.",
    },
    {
        "id": "demiurge", "definition": "A secondary creator deity.",
        "node_id": "concept.demiurge",
        "family_id": "cosmology.cosmic_agents",
        "family_label": "Cosmic Agents",
        "family_definition": "Beings or powers acting on the cosmos.",
        "domain_id": "cosmology", "domain_label": "Cosmology",
        "domain_definition": "Origin and structure of the universe.",
    },
    {
        "id": "covenant", "definition": "A binding divine-human agreement.",
        "node_id": "concept.covenant",
        "family_id": "theology.divine_attributes_and_acts",
        "family_label": "Divine Attributes And Acts",
        "family_definition": "What God reveals or does.",
        "domain_id": "theology", "domain_label": "Theology",
        "domain_definition": "The nature of the divine.",
    },
]


def test_prompt_version_bumped():
    assert PROMPT_VERSION == "v2"


# ── load_taxonomy enrichment ─────────────────────────────────────────────────


def test_load_taxonomy_enriches_and_orders():
    concepts = load_taxonomy()
    assert concepts, "taxonomy should not be empty"
    sample = concepts[0]
    for k in ("family_id", "family_label", "domain_id", "domain_label"):
        assert sample.get(k), f"{k} missing/empty"
    # sorted by (domain, family, concept)
    keys = [(c["domain_id"], c["family_id"], c["id"]) for c in concepts]
    assert keys == sorted(keys)


# ── build_prompt grouped rendering ───────────────────────────────────────────


def test_grouped_headers_and_glosses():
    prompt = build_prompt("a passage", "Cite", ENRICHED)
    assert "Concepts (grouped by domain → family):" in prompt
    # domain header with its gloss
    assert "# Cosmology — Origin and structure of the universe." in prompt
    assert "# Theology — The nature of the divine." in prompt
    # family header with its gloss
    assert "## Divine Structure — The architecture of the highest realms." in prompt
    assert "## Cosmic Agents — Beings or powers acting on the cosmos." in prompt
    # concept bullets carry id + definition
    assert "- monad:" in prompt
    assert "The absolutely simple first principle." in prompt


def test_concepts_grouped_under_correct_domain():
    prompt = build_prompt("body", "Cite", ENRICHED)
    cosmology_at = prompt.index("# Cosmology")
    theology_at = prompt.index("# Theology")
    # cosmology concepts appear before the theology header; covenant after it
    assert prompt.index("- monad:") < theology_at
    assert prompt.index("- demiurge:") < theology_at
    assert prompt.index("- covenant:") > theology_at
    assert cosmology_at < theology_at


def test_output_contract_unchanged():
    """The JSON output schema the model must return is still the v1 schema."""
    prompt = build_prompt("body", "Cite", ENRICHED)
    for field in ("concept_id", "score", "justification", "is_new_concept", "new_concept_def"):
        assert field in prompt
    # no leftover flat JSON-array concept block header
    assert "\nConcepts:\n[\n" not in prompt


def test_body_still_passed_through():
    body = "z" * 4000
    prompt = build_prompt(body, "Cite", ENRICHED)
    assert body in prompt


def test_real_taxonomy_renders_six_domains():
    """End-to-end with the live taxonomy: all six domain headers present."""
    prompt = build_prompt("body", "Cite", load_taxonomy())
    for dom in ("# Cosmology", "# Soteriology", "# Theology",
                "# Praxis", "# Anthropology", "# Ethics"):
        assert dom in prompt, f"missing domain header {dom!r}"
