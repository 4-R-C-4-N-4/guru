"""
test_workbook.py — the two pipeline graphs must not describe commands that
do not work.

Every HIGH finding in the first review of this workbook was the same mistake:
a command written into a node's `command`/`gate` field, printed by
`guru ingest status` as the literal next thing to run, that had never been
executed. `review_edges.py --text X` (no such flag), `review_dossiers.py
sample --field F --level N` (mutually exclusive), and a node whose gate
pointed at a raw file that multi-page sources never produce.

A driver following the CLI hits an argparse error. That class of defect is
cheap to catch statically, so it is caught here.
"""

from __future__ import annotations

import re
import shlex
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from guru import dossier, ingest  # noqa: E402

GRAPHS = {"ingest": ingest.NODES, "dossier": dossier.NODES}
ALL_NODES = [(g, n) for g, nodes in GRAPHS.items() for n in nodes]


# ---------------------------------------------------------------- helpers


def _script_of(command: str) -> Path | None:
    """The scripts/*.py a command invokes, if it invokes one."""
    for tok in shlex.split(command):
        if tok.endswith(".py") and tok.startswith("scripts/"):
            return PROJECT_ROOT / tok
    return None


def _is_placeholder(tok: str) -> bool:
    return tok.startswith("<") or tok.startswith("{") or tok.startswith("[")


def _declared_flags(source: str) -> set[str]:
    return set(re.findall(r"""add_argument\(\s*["'](--[a-z0-9-]+)["']""", source))


def _declared_subcommands(source: str) -> set[str]:
    return set(re.findall(r"""add_parser\(\s*["']([a-z0-9-]+)["']""", source))


def _commands():
    for graph, node in ALL_NODES:
        for slot in ("command", "gate"):
            raw = getattr(node, slot)
            if raw:
                yield graph, node.key, slot, raw


# ---------------------------------------------------------------- graph shape


@pytest.mark.parametrize("graph,node", ALL_NODES, ids=lambda x: getattr(x, "key", x))
def test_every_node_has_a_workbook_file(graph, node):
    assert (PROJECT_ROOT / node.doc).is_file(), f"{node.key} promises {node.doc}"


@pytest.mark.parametrize("graph,subdir", [("ingest", "docs/ingest"), ("dossier", "docs/dossiers")])
def test_no_orphan_workbook_files(graph, subdir):
    pattern = "[0-9]*.md" if graph == "ingest" else "D*.md"
    on_disk = {p.stem for p in (PROJECT_ROOT / subdir).glob(pattern)}
    keys = {n.key for n in GRAPHS[graph]}
    assert on_disk == keys, f"{subdir}: {on_disk ^ keys} is in one place only"


@pytest.mark.parametrize("graph,node", ALL_NODES, ids=lambda x: getattr(x, "key", x))
def test_declared_contract_exists(graph, node):
    if not node.contract:
        pytest.skip("no contract")
    assert (PROJECT_ROOT / node.contract).is_file()


# ---------------------------------------------------------------- commands


@pytest.mark.parametrize("graph,key,slot,command", list(_commands()),
                         ids=lambda x: x if isinstance(x, str) else "")
def test_command_names_a_real_script(graph, key, slot, command):
    for tok in shlex.split(command):
        if tok.endswith(".py"):
            assert (PROJECT_ROOT / tok).is_file(), f"{key}.{slot}: no such script {tok}"


@pytest.mark.parametrize("graph,key,slot,command", list(_commands()),
                         ids=lambda x: x if isinstance(x, str) else "")
def test_command_flags_are_accepted_by_the_script(graph, key, slot, command):
    """Every --flag a node prints must exist in the target script's argparse.

    This is the check that `review_edges.py --text` would have failed.
    """
    script = _script_of(command)
    if script is None:
        pytest.skip("not a scripts/*.py invocation")

    source = script.read_text()
    declared = _declared_flags(source)
    used = {t for t in shlex.split(command) if t.startswith("--")}
    unknown = used - declared
    assert not unknown, f"{key}.{slot}: {script.name} does not accept {sorted(unknown)}"


@pytest.mark.parametrize("graph,key,slot,command", list(_commands()),
                         ids=lambda x: x if isinstance(x, str) else "")
def test_command_subcommand_exists(graph, key, slot, command):
    script = _script_of(command)
    if script is None:
        pytest.skip("not a scripts/*.py invocation")

    source = script.read_text()
    subs = _declared_subcommands(source)
    if not subs:
        pytest.skip("script has no subparsers")

    toks = shlex.split(command)
    script_at = next(i for i, t in enumerate(toks) if t.endswith(".py"))
    after = [t for t in toks[script_at + 1:] if not t.startswith("-")]
    if not after or _is_placeholder(after[0]):
        pytest.skip("no literal subcommand given")
    assert after[0] in subs, f"{key}.{slot}: {script.name} has no `{after[0]}` subcommand"


def test_review_dossiers_sample_is_not_given_both_selectors():
    """`sample` raises SystemExit when --field and --level are both passed.

    Static flag checking cannot see a mutual exclusion enforced in the body,
    and this specific pair is what D3 printed for its whole first draft.
    """
    node = dossier.NODES_BY_KEY["D3-review"]
    toks = shlex.split(node.command)
    assert not ("--field" in toks and "--level" in toks), (
        "review_dossiers.py sample takes exactly one of --field / --level")


# ---------------------------------------------------------------- docs


@pytest.mark.parametrize("md", sorted(
    list((PROJECT_ROOT / "docs/ingest").glob("**/*.md"))
    + list((PROJECT_ROOT / "docs/dossiers").glob("**/*.md"))
    + [PROJECT_ROOT / "AGENTS.md", PROJECT_ROOT / "CLAUDE.md"]),
    ids=lambda p: str(p.relative_to(PROJECT_ROOT)))
def test_relative_links_resolve(md):
    broken = [
        link for _, link in re.findall(r"\[([^\]]+)\]\(([^)]+)\)", md.read_text())
        if not link.startswith(("http", "#")) and not (md.parent / link).resolve().exists()
    ]
    assert not broken, f"{md.name}: {broken}"


@pytest.mark.parametrize("contract", sorted(
    list((PROJECT_ROOT / "prompts/ingest").glob("*.md"))
    + list((PROJECT_ROOT / "prompts/dossier/contracts").glob("*.md")),
    ), ids=lambda p: p.stem)
def test_contract_parses_and_binds_every_declared_input(contract):
    from run_contract import load_contract, split_sections

    front, body = load_contract(str(contract))
    system, task = split_sections(body)

    for name in front.get("inputs", {}):
        assert "{{" + name + "}}" in task, (
            f"{contract.stem}: declares input `{name}` but never uses it in ## Task")

    stranded = re.findall(r"\{\{(\w+)\}\}", system)
    assert not stranded, f"{contract.stem}: placeholders in ## System are never filled: {stranded}"

    unknown = set(re.findall(r"\{\{(\w+)\}\}", task)) - set(front.get("inputs", {}))
    assert not unknown, f"{contract.stem}: ## Task uses undeclared inputs {sorted(unknown)}"
