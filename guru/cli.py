"""
guru/cli.py — Guru interactive query CLI.

Usage:
    python3 -m guru query "What is the role of divine light in Gnostic thought?"
    python3 -m guru query "..." --tradition gnosticism --no-hermeticism
    python3 -m guru query "..." --verbose
    python3 -m guru interactive
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import tomllib

from guru.paths import CONFIG_EMBEDDING as CONFIG_PATH, SCRIPTS_DIR

sys.path.insert(0, str(SCRIPTS_DIR))

from guru.model import ModelProvider
from guru.preferences import UserPreferences
from guru.prompt import build_prompt
from guru.retriever import HybridRetriever


def embed_query(query: str) -> list[float]:
    """Embed a query string using the configured embedding model."""
    with open(CONFIG_PATH, "rb") as f:
        cfg = tomllib.load(f)
    model_cfg = cfg.get("model", {})
    provider = model_cfg.get("provider", "ollama")
    model_name = model_cfg.get("model_name", "nomic-embed-text")

    if provider == "ollama":
        from llm import ollama_embed_url
        payload = json.dumps({"model": model_name, "input": query}).encode()
        req = urllib.request.Request(
            ollama_embed_url(),
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["embeddings"][0]
    elif provider == "sentence_transformers":
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(model_name).encode([query]).tolist()[0]
    else:
        raise ValueError(f"Embedding not supported for provider: {provider}")


def run_query(
    query: str,
    prefs: UserPreferences,
    verbose: bool = False,
    top_k: int | None = None,
) -> str:
    t0 = time.time()

    if verbose:
        print(f"\n[guru] Embedding query...", file=sys.stderr)
    qemb = embed_query(query)

    if verbose:
        print(f"[guru] Retrieving chunks...", file=sys.stderr)
    retriever = HybridRetriever()
    chunks = retriever.retrieve(query, qemb, prefs, top_k=top_k)

    if verbose:
        print(f"[guru] Retrieved {len(chunks)} chunks:", file=sys.stderr)
        for c in chunks:
            print(f"  [{c.tradition} | {c.text_name} | {c.section}] sim={c.similarity:.3f} tier={c.tier}", file=sys.stderr)

    if not chunks:
        return "(No relevant passages found for this query. Try broadening your question.)"

    system_prompt = build_prompt(query, chunks, prefs)

    if verbose:
        print(f"[guru] Generating response...", file=sys.stderr)

    model = ModelProvider()
    response = model.generate(system=system_prompt, prompt=query)

    elapsed = time.time() - t0

    # Stats footer
    traditions = sorted({c.tradition for c in chunks})
    footer = (
        f"\n\n---\n"
        f"Sources: {len(chunks)} chunks from {', '.join(traditions)} | "
        f"Model: {model.model} | "
        f"Elapsed: {elapsed:.1f}s"
    )

    return response + footer


def build_prefs_from_args(args: argparse.Namespace) -> UserPreferences:
    """Build UserPreferences from CLI flags."""
    blacklist = getattr(args, "exclude_tradition", []) or []
    whitelist = getattr(args, "tradition", []) or []

    if whitelist:
        return UserPreferences(mode="whitelist", whitelisted_traditions=whitelist)
    if blacklist:
        return UserPreferences(mode="blacklist", blacklisted_traditions=blacklist)
    return UserPreferences.allow_all()


def cmd_query(args: argparse.Namespace) -> None:
    prefs = build_prefs_from_args(args)
    print(f"\nActive traditions: {prefs.active_tradition_summary()}\n", file=sys.stderr)
    result = run_query(args.query, prefs, verbose=args.verbose)
    print(result)


def cmd_interactive(args: argparse.Namespace) -> None:
    prefs = build_prefs_from_args(args)
    print(f"Guru — comparative esoteric scholar")
    print(f"Active traditions: {prefs.active_tradition_summary()}")
    print("Type your question (blank line to exit)\n")

    while True:
        try:
            query = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break
        if not query:
            break
        result = run_query(query, prefs, verbose=args.verbose)
        print(f"\nGuru:\n{result}\n")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="guru",
        description="Guru — comparative esoteric scholar with citation-grounded responses",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # guru query "..."
    qp = sub.add_parser("query", help="Ask a single question")
    qp.add_argument("query", help="Question to ask")
    qp.add_argument("--tradition", nargs="+", metavar="T",
                    help="Whitelist: only include these traditions")
    qp.add_argument("--exclude-tradition", nargs="+", metavar="T",
                    help="Blacklist: exclude these traditions")
    qp.add_argument("--top-k", type=int, default=None)
    qp.add_argument("--verbose", "-v", action="store_true")
    qp.set_defaults(func=cmd_query)

    # guru interactive
    ip = sub.add_parser("interactive", help="Interactive query loop")
    ip.add_argument("--tradition", nargs="+", metavar="T")
    ip.add_argument("--exclude-tradition", nargs="+", metavar="T")
    ip.add_argument("--verbose", "-v", action="store_true")
    ip.set_defaults(func=cmd_interactive)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
