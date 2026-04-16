"""
validate_index.py — Verify the vector store and corpus are in sync.

Checks:
  1. Vector count == chunk count
  2. Every chunk ID in corpus/ has a corresponding vector
  3. Similarity spot-check: "divine light within all things" returns
     expected chunks (Gospel of Thomas Logion 77)
  4. Tradition exclusion filter works correctly

Usage:
    python3 scripts/validate_index.py [--verbose]
"""

import logging
import sys
from pathlib import Path

import tomllib

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
CORPUS_DIR = PROJECT_ROOT / "corpus"
CONFIG_PATH = PROJECT_ROOT / "config" / "embedding.toml"


def collect_chunk_ids() -> list[str]:
    ids = []
    for trad_dir in sorted(CORPUS_DIR.iterdir()):
        if not trad_dir.is_dir() or trad_dir.name.endswith(".toml"):
            continue
        for text_dir in sorted(trad_dir.iterdir()):
            if not text_dir.is_dir():
                continue
            for chunk_file in sorted((text_dir / "chunks").glob("*.toml")):
                with open(chunk_file, "rb") as f:
                    d = tomllib.load(f)
                ids.append(d["chunk"]["id"])
    return ids


def embed_query(query: str, config_path: Path) -> list[float]:
    with open(config_path, "rb") as f:
        cfg = tomllib.load(f)
    model_cfg = cfg.get("model", {})
    provider = model_cfg.get("provider", "ollama")
    model_name = model_cfg.get("model_name", "nomic-embed-text")

    if provider == "ollama":
        import json
        import urllib.request
        payload = json.dumps({"model": model_name, "input": query}).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())["embeddings"][0]
    elif provider == "sentence_transformers":
        from sentence_transformers import SentenceTransformer
        return SentenceTransformer(model_name).encode([query]).tolist()[0]
    else:
        raise ValueError(f"Unsupported provider for validation: {provider}")


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Validate vector index")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        stream=sys.stderr,
    )

    sys.path.insert(0, str(Path(__file__).parent))
    from vector_store import VectorStore
    vs = VectorStore(CONFIG_PATH)

    corpus_ids = collect_chunk_ids()
    vector_count = vs.count()

    print(f"\n=== Guru Vector Index Validation ===")
    print(f"Corpus chunks : {len(corpus_ids)}")
    print(f"Vector count  : {vector_count}")

    # Check 1: counts match
    if vector_count == len(corpus_ids):
        print("✓ Count check PASSED")
    else:
        print(f"✗ Count check FAILED (diff={vector_count - len(corpus_ids)})")

    # Check 2: every chunk ID has a vector
    missing = [cid for cid in corpus_ids if not vs.exists(cid)]
    if not missing:
        print(f"✓ ID coverage PASSED (all {len(corpus_ids)} chunks present)")
    else:
        print(f"✗ ID coverage FAILED — {len(missing)} missing: {missing[:5]}")

    # Check 3: similarity spot-check
    print("\n--- Similarity spot-check: 'divine light within all things' ---")
    try:
        qemb = embed_query("divine light within all things", CONFIG_PATH)
        results = vs.query(embedding=qemb, top_n=5)
        found_logion77 = False
        for r in results:
            mark = "✓" if "077" in r["chunk_id"] or "Logion 77" in r.get("metadata", {}).get("section", "") else " "
            print(f"  {mark} {r['chunk_id']:<50} sim={r['similarity']:.3f}  {r.get('metadata',{}).get('section','')}")
            if "077" in r["chunk_id"]:
                found_logion77 = True
        if found_logion77:
            print("✓ Spot-check PASSED (Logion 77 in top-5)")
        else:
            print("△ Spot-check: Logion 77 not in top-5 (may need more corpus)")
    except Exception as e:
        print(f"  Error during spot-check: {e}")

    # Check 4: tradition exclusion filter
    print("\n--- Filter check: exclude gnosticism ---")
    try:
        results_excl = vs.query(embedding=qemb, top_n=5, exclude_tradition="gnosticism")
        leaked = [r for r in results_excl if r.get("metadata", {}).get("tradition") == "gnosticism"]
        if not leaked:
            print(f"✓ Filter check PASSED (no gnosticism in results)")
        else:
            print(f"✗ Filter check FAILED — {len(leaked)} gnosticism chunks leaked")
    except Exception as e:
        print(f"  Error during filter check: {e}")

    print()


if __name__ == "__main__":
    main()
