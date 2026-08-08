#!/usr/bin/env python3
"""
run_contract.py — execute a judgement contract from prompts/ingest/.

The judgement nodes of the ingest pipeline (see docs/ingest/README.md) are
specified as contracts rather than as conversations, so that the same call can
be made by a local model or by whichever agent is driving, with the same
inputs and the same output shape either way. This runner is the local-model
half of that equivalence:

    python3 scripts/run_contract.py chunk-config \\
        --input raw_head=raw/celtic/mabinogion.txt \\
        --var source_id=mabinogion --var tradition=celtic

An agent driving by hand reads prompts/ingest/chunk-config.md and produces the
same JSON. Neither path is privileged.

Contract format — TOML frontmatter between `---` fences, then markdown:

    ---
    id = "chunk-config"
    max_tokens = 4096
    required_keys = ["strategy", "rationale"]
    [inputs]
    raw_head = "head and tail of the raw text, within the char budget"
    ---

    ## System
    <system prompt>

    ## Task
    <task, referencing {{raw_head}} and {{source_id}}>

Placeholders are `{{name}}` — double-braced so they do not collide with the
JSON braces that contracts carry in their output-schema sections.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import tomllib

PROJECT_ROOT = Path(__file__).parent.parent
CONTRACT_DIR = PROJECT_ROOT / "prompts" / "ingest"

sys.path.insert(0, str(Path(__file__).parent))

from llm import call_llm, parse_json_response  # noqa: E402

DEFAULT_CHAR_BUDGET = 12000


def load_contract(name: str) -> tuple[dict, str]:
    """Return (frontmatter, body) for a contract by id or path."""
    path = Path(name)
    if not path.is_file():
        path = CONTRACT_DIR / f"{name}.md"
    if not path.is_file():
        available = sorted(p.stem for p in CONTRACT_DIR.glob("*.md"))
        raise SystemExit(f"no contract {name!r}; available: {', '.join(available)}")

    text = path.read_text()
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.DOTALL)
    if not m:
        raise SystemExit(f"{path}: missing TOML frontmatter between --- fences")
    return tomllib.loads(m.group(1)), m.group(2)


def split_sections(body: str) -> tuple[str, str]:
    """Split the markdown body into (system, task) on `## System` / `## Task`."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in body.splitlines():
        heading = re.match(r"^##\s+(\w+)\s*$", line)
        if heading:
            current = heading.group(1).lower()
            sections[current] = []
            continue
        if current:
            sections[current].append(line)

    if "system" not in sections or "task" not in sections:
        raise SystemExit("contract body needs both a `## System` and a `## Task` section")
    return ("\n".join(sections["system"]).strip(),
            "\n".join(sections["task"]).strip())


def read_input(spec: str, budget: int) -> tuple[str, str]:
    """`name=path` → (name, contents), keeping head and tail within a char budget.

    Budgeting is by character, not by line. Gutenberg and sacred-texts bodies
    routinely store a whole paragraph — sometimes a whole work — as a single
    line, so a line count is not a size bound.
    """
    if "=" not in spec:
        raise SystemExit(f"--input expects name=path, got {spec!r}")
    name, _, raw_path = spec.partition("=")
    p = Path(raw_path)
    if not p.is_file():
        raise SystemExit(f"--input {name}: no such file {p}")

    text = p.read_text(errors="replace")
    if budget and len(text) > budget:
        half = budget // 2
        elided = len(text) - budget
        text = (text[:half]
                + f"\n\n[... {elided:,} characters elided ...]\n\n"
                + text[-half:])
    return name, text


def substitute(text: str, values: dict[str, str]) -> str:
    for key, val in values.items():
        text = text.replace("{{" + key + "}}", val)
    leftover = re.findall(r"\{\{(\w+)\}\}", text)
    if leftover:
        raise SystemExit("unfilled placeholders: " + ", ".join(sorted(set(leftover))))
    return text


def main() -> None:
    ap = argparse.ArgumentParser(description="Run an ingest judgement contract")
    ap.add_argument("contract", help="contract id (e.g. chunk-config) or path")
    ap.add_argument("--input", action="append", default=[], metavar="NAME=PATH",
                    help="bind a file's contents to a placeholder")
    ap.add_argument("--var", action="append", default=[], metavar="NAME=VALUE",
                    help="bind a literal string to a placeholder")
    ap.add_argument("--budget", type=int, default=DEFAULT_CHAR_BUDGET, metavar="CHARS",
                    help="character budget per --input file, split evenly between "
                         "head and tail (0 = whole file). Boilerplate lives at the "
                         "edges, which is why the middle is what drops.")
    ap.add_argument("--provider", default="llamacpp")
    ap.add_argument("--model", default="Qwen3.5-27B-UD-Q4_K_XL.gguf")
    ap.add_argument("--max-tokens", type=int, default=0,
                    help="override the contract's max_tokens")
    ap.add_argument("--print-prompt", action="store_true",
                    help="render the prompt and exit without calling a model — "
                         "this is what you paste to a driving agent")
    args = ap.parse_args()

    front, body = load_contract(args.contract)
    system, task = split_sections(body)

    values: dict[str, str] = {}
    for spec in args.var:
        if "=" not in spec:
            raise SystemExit(f"--var expects name=value, got {spec!r}")
        k, _, v = spec.partition("=")
        values[k] = v
    for spec in args.input:
        name, content = read_input(spec, args.budget)
        values[name] = content

    declared = set(front.get("inputs", {}))
    missing = declared - set(values)
    if missing:
        raise SystemExit("contract declares inputs not provided: " + ", ".join(sorted(missing)))

    prompt = substitute(task, values)

    if args.print_prompt:
        print(f"=== SYSTEM ===\n{system}\n\n=== TASK ===\n{prompt}")
        return

    max_tokens = args.max_tokens or int(front.get("max_tokens", 4096))
    raw = call_llm(provider=args.provider, model=args.model,
                   system=system, prompt=prompt, max_tokens=max_tokens)

    parsed = parse_json_response(raw)
    if not parsed:
        print(raw, file=sys.stderr)
        raise SystemExit("contract returned no parseable JSON — raw response above")

    required = front.get("required_keys", [])
    if isinstance(parsed, dict):
        absent = [k for k in required if k not in parsed]
        if absent:
            print(json.dumps(parsed, indent=2), file=sys.stderr)
            raise SystemExit("response missing required keys: " + ", ".join(absent))

    print(json.dumps(parsed, indent=2))


if __name__ == "__main__":
    main()
