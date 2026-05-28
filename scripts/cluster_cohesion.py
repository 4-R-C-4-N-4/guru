#!/usr/bin/env python3
"""cluster_cohesion.py — silhouette analysis of the concept→family clustering.

Embeds every concept definition from concepts/taxonomy.toml with the corpus
embedder (config/embedding.toml — ollama/nomic-embed-text) and scores how well
each concept fits its assigned family (design.md §4) via a cosine-distance
silhouette:

    s_i = (b_i - a_i) / max(a_i, b_i)

  a_i = mean cosine distance to the *other* concepts in the same family (cohesion)
  b_i = min over other families of the mean distance to that family (separation)

s_i < 0 means a concept sits (slightly) closer to some other family than its own.

IMPORTANT — read docs/concept-hierarchy/cluster-cohesion-analysis.md before acting
on the output. On this taxonomy the silhouettes are near zero across the board
(mean ≈ -0.05): the embedder does not separate the concepts at family granularity
because the definitions share heavy surface vocabulary and the families encode
role/function distinctions embeddings don't capture. Treat only large-magnitude,
semantically-corroborated scores as signal — the sign alone is mostly noise.

Read-only (no DB, no writes). Reusable: re-run after any clustering change.

    python scripts/cluster_cohesion.py [--misfit -0.10] [--top N]

Requires ollama up with the configured embedding model pulled.
"""
from __future__ import annotations

import argparse
import math
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
TAXONOMY_TOML = PROJECT_ROOT / "concepts" / "taxonomy.toml"
EMBEDDING_TOML = PROJECT_ROOT / "config" / "embedding.toml"
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))


def load_assignment() -> tuple[dict[str, str], dict[str, str]]:
    """Return ({cid: definition}, {cid: family_id}) from the clustered TOML."""
    data = tomllib.loads(TAXONOMY_TOML.read_text())
    defn, fam_of = {}, {}
    for domain, fams in data.get("concepts", {}).items():
        for fam_key, members in fams.items():
            for cid, d in members.items():
                defn[cid] = d
                fam_of[cid] = f"{domain}.{fam_key}"
    return defn, fam_of


def embed_definitions(defn: dict[str, str]) -> dict[str, list[float]]:
    """Embed each definition with the configured corpus model (normalized)."""
    cfg = tomllib.loads(EMBEDDING_TOML.read_text())["model"]
    model = cfg["model_name"]
    from embed_corpus import embed_ollama  # same path the corpus uses

    cids = sorted(defn)
    vecs = embed_ollama([defn[c] for c in cids], model)
    out = {}
    for c, v in zip(cids, vecs):
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        out[c] = [x / n for x in v]
    return out


def silhouettes(emb: dict[str, list[float]], fam_of: dict[str, str]):
    """Per-concept silhouette + nearest other family. Returns {cid: (s, a, nearest_family, b)}."""
    cids = sorted(emb)
    fams: dict[str, list[str]] = {}
    for c in cids:
        fams.setdefault(fam_of[c], []).append(c)

    def dist(a: str, b: str) -> float:
        return 1.0 - sum(x * y for x, y in zip(emb[a], emb[b]))  # unit vectors

    result = {}
    for c in cids:
        own = [o for o in fams[fam_of[c]] if o != c]
        a = sum(dist(c, o) for o in own) / len(own) if own else 0.0
        best_b, best_f = math.inf, None
        for f, members in fams.items():
            if f == fam_of[c]:
                continue
            b = sum(dist(c, o) for o in members) / len(members)
            if b < best_b:
                best_b, best_f = b, f
        s = (best_b - a) / max(a, best_b) if max(a, best_b) > 0 else 0.0
        result[c] = (s, a, best_f, best_b)
    return result, fams


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--misfit", type=float, default=-0.10,
                   help="silhouette below this is reported as a (candidate) mis-fit. Default -0.10.")
    p.add_argument("--top", type=int, default=0,
                   help="limit the mis-fit list to the N worst (0 = all).")
    args = p.parse_args()

    defn, fam_of = load_assignment()
    print(f"embedding {len(defn)} concept definitions ...", file=sys.stderr)
    emb = embed_definitions(defn)
    sil, fams = silhouettes(emb, fam_of)

    mean_s = sum(v[0] for v in sil.values()) / len(sil)
    print(f"\n=== mean silhouette = {mean_s:+.3f}  (near 0 ⇒ families not separable in embedding space) ===")

    print("\n=== per-family mean silhouette (loosest first) ===")
    fam_mean = {f: sum(sil[c][0] for c in m) / len(m) for f, m in fams.items()}
    for f in sorted(fam_mean, key=fam_mean.get):
        print(f"  {fam_mean[f]:+.3f}  {f}  (n={len(fams[f])})")

    misfits = sorted((c for c in sil if sil[c][0] < args.misfit), key=lambda c: sil[c][0])
    if args.top:
        misfits = misfits[:args.top]
    print(f"\n=== candidate mis-fits (silhouette < {args.misfit}) — corroborate semantically before acting ===")
    for c in misfits:
        s, a, nf, b = sil[c]
        print(f"  s={s:+.3f}  {c:24} {fam_of[c]:34} → nearer: {nf}")
    if not misfits:
        print("  (none below threshold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
