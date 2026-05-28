#!/usr/bin/env python3
"""sync_taxonomy.py — populate the concept-hierarchy tables from taxonomy.toml.

Reads concepts/taxonomy.toml and upserts the four concept-hierarchy tables
created by scripts/migrations/v3_006_concept_families.sql:

  concept_families            — domains (parent_id NULL) + families (parent_id → domain)
  concept_family_membership   — primary memberships (is_primary = 1) from the TOML
  concept_aliases             — concept synonyms from the [concept_aliases] section
  family_aliases              — family/domain synonyms from inline `aliases = [...]`

Idempotent — safe to run on every TOML edit. Default is --dry-run (summary
only, no writes); --apply commits inside a transaction. Same defaulting
discipline as auto_promote.py / cleanup_dupes.sh.

    sync_taxonomy.py [--db PATH] [--dry-run | --apply]

Per docs/concept-hierarchy/design.md §7 (todo:0a25044c, parent 10512e6a).

Notes on the data model (design.md §5, §7):
  - Concept nodes are stored in `nodes` with id `concept.<cid>`; membership and
    concept-alias rows reference that id, not the bare TOML key.
  - Concept node upsert mirrors promote_to_expresses (review_tags.py): it
    COALESCEs the definition so an existing (possibly hand-curated) definition
    is preserved — definition drift is a deliberate manual operation (§15). The
    upsert exists so a TOML concept that no chunk has tagged yet still gets a
    node, satisfying the membership FK.
  - Family `label` is derived from the id's last segment ("cosmic_agents" →
    "Cosmic Agents", §5.1) unless the TOML supplies an explicit `label`.
  - Aliases are lowercased Python-side (Unicode-aware str.lower(), §5.1) before
    INSERT, so SQLite's ASCII-range CHECK(alias = LOWER(alias)) is satisfied.

What the sync does NOT do (design.md §7):
  - Does not write or delete is_primary = 0 (secondary) rows — those come from
    review actions only. A move demotes a prior primary to secondary rather
    than deleting it (conservative default; a --strict-primary clean-cut and a
    --prune for empty families are documented in §7 but out of scope here).
  - Does not delete families / memberships / aliases that vanish from the TOML
    (except the scoped alias-replace for owners present in the TOML).
  - Does not rewrite edges or staged_tags; family changes are pure metadata.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import tomllib
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DB = PROJECT_ROOT / "data" / "guru.db"
TAXONOMY_TOML = PROJECT_ROOT / "concepts" / "taxonomy.toml"

# Scalar/array keys carried by a [families.*] block — everything else that is a
# table is a child family.
_FAMILY_META_KEYS = {"label", "definition", "aliases"}


def _label_from_id(family_id: str) -> str:
    """Derive a prompt-facing label from a family id's last dotted segment."""
    return family_id.split(".")[-1].replace("_", " ").title()


# ── parse ────────────────────────────────────────────────────────────────────

def parse_taxonomy(data: dict) -> dict:
    """Build the expected DB state from a parsed taxonomy.toml dict.

    Returns:
      families:        [(id, parent_id, label, definition)] — domains first,
                       each immediately followed by its child families, so a
                       parent row always precedes a child (FK-safe insert order).
      family_aliases:  {family_id: [alias, ...]}
      concepts:        [(node_id, label, definition, family_id)]
      concept_aliases: {node_id: [alias, ...]}
    """
    families: list[tuple[str, str | None, str, str]] = []
    family_aliases: dict[str, list[str]] = {}

    for dom_id, dom_body in data.get("families", {}).items():
        if not isinstance(dom_body, dict):
            raise SystemExit(f"[families.{dom_id}] is not a table")
        dom_def = dom_body.get("definition")
        if not dom_def:
            raise SystemExit(f"domain [families.{dom_id}] missing required definition")
        families.append((dom_id, None, dom_body.get("label") or _label_from_id(dom_id), dom_def))
        if dom_body.get("aliases"):
            family_aliases[dom_id] = list(dom_body["aliases"])
        # child families: any sub-table under the domain
        for key, val in dom_body.items():
            if key in _FAMILY_META_KEYS or not isinstance(val, dict):
                continue
            fid = f"{dom_id}.{key}"
            fdef = val.get("definition")
            if not fdef:
                raise SystemExit(f"family [families.{fid}] missing required definition")
            families.append((fid, dom_id, val.get("label") or _label_from_id(fid), fdef))
            if val.get("aliases"):
                family_aliases[fid] = list(val["aliases"])

    declared = {f[0] for f in families}
    concepts: list[tuple[str, str, str, str]] = []
    for dom_id, fams in data.get("concepts", {}).items():
        for fam_key, members in fams.items():
            family_id = f"{dom_id}.{fam_key}"
            if family_id not in declared:
                raise SystemExit(
                    f"[concepts.{dom_id}.{fam_key}] references undeclared family "
                    f"[families.{family_id}]"
                )
            if not isinstance(members, dict):
                raise SystemExit(f"[concepts.{dom_id}.{fam_key}] is not a concept table")
            for cid, definition in members.items():
                if not isinstance(definition, str):
                    raise SystemExit(
                        f"[concepts.{dom_id}.{fam_key}].{cid} is not a string definition"
                    )
                concepts.append(
                    (f"concept.{cid}", cid.replace("_", " ").title(), definition, family_id)
                )

    concept_aliases = {
        f"concept.{cid}": list(aliases)
        for cid, aliases in data.get("concept_aliases", {}).items()
    }
    return {
        "families": families,
        "family_aliases": family_aliases,
        "concepts": concepts,
        "concept_aliases": concept_aliases,
    }


# ── sync ───────────────────────────────────────────────────────────────────--

def sync(conn: sqlite3.Connection, plan: dict, apply: bool) -> dict:
    """Apply the plan inside a transaction, compute the report from the
    resulting state, then COMMIT (apply) or ROLLBACK (dry-run).

    The connection must be in autocommit mode (isolation_level=None) with
    foreign_keys enabled; main() and the tests set both.
    """
    cur = conn.cursor()

    # Snapshot the current primary map before writing (for the delta counts).
    before_primary = dict(
        cur.execute(
            "SELECT concept_id, family_id FROM concept_family_membership WHERE is_primary = 1"
        ).fetchall()
    )

    conn.execute("BEGIN")
    try:
        # 2. upsert families (TOML-owned: overwrite parent/label/definition)
        for fid, parent, label, definition in plan["families"]:
            cur.execute(
                """INSERT INTO concept_families(id, parent_id, label, definition)
                   VALUES(?, ?, ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     parent_id  = excluded.parent_id,
                     label      = excluded.label,
                     definition = excluded.definition""",
                (fid, parent, label, definition),
            )

        # 3. upsert concept nodes (COALESCE preserves an existing definition)
        for node_id, label, definition, _family in plan["concepts"]:
            cur.execute(
                """INSERT INTO nodes(id, type, label, definition)
                   VALUES(?, 'concept', ?, ?)
                   ON CONFLICT(id) DO UPDATE SET
                     definition = COALESCE(nodes.definition, excluded.definition)""",
                (node_id, label, definition),
            )

        # 4. primary memberships — demote any other primary, then upsert target.
        #    Order matters: demoting first keeps at most one is_primary=1 row per
        #    concept at every step, so the partial unique index never trips.
        demoted = 0
        for node_id, _label, _definition, family_id in plan["concepts"]:
            demoted += cur.execute(
                """UPDATE concept_family_membership SET is_primary = 0
                   WHERE concept_id = ? AND is_primary = 1 AND family_id <> ?""",
                (node_id, family_id),
            ).rowcount
            cur.execute(
                """INSERT INTO concept_family_membership(concept_id, family_id, is_primary)
                   VALUES(?, ?, 1)
                   ON CONFLICT(concept_id, family_id) DO UPDATE SET is_primary = 1""",
                (node_id, family_id),
            )

        # 5. replace alias rows for owners mentioned in the TOML (lowercased).
        for family_id, aliases in plan["family_aliases"].items():
            cur.execute("DELETE FROM family_aliases WHERE family_id = ?", (family_id,))
            for alias in aliases:
                cur.execute(
                    "INSERT INTO family_aliases(family_id, alias) VALUES(?, ?)",
                    (family_id, alias.lower()),
                )
        for node_id, aliases in plan["concept_aliases"].items():
            cur.execute("DELETE FROM concept_aliases WHERE concept_id = ?", (node_id,))
            for alias in aliases:
                cur.execute(
                    "INSERT INTO concept_aliases(concept_id, alias) VALUES(?, ?)",
                    (node_id, alias.lower()),
                )

        # ── deltas (vs before-snapshot) ──
        target_primary = {c[0]: c[3] for c in plan["concepts"]}
        created = sum(1 for n in target_primary if n not in before_primary)
        unchanged = sum(1 for n, f in target_primary.items() if before_primary.get(n) == f)
        moves = [
            (n, before_primary[n], f)
            for n, f in target_primary.items()
            if n in before_primary and before_primary[n] != f
        ]

        # ── worklists (queried from the post-write state) ──
        report = {
            "families_upserted": len(plan["families"]),
            "concepts_upserted": len(plan["concepts"]),
            "primaries_created": created,
            "primaries_unchanged": unchanged,
            "primaries_moved": len(moves),
            "moves": moves,
            "primaries_demoted": demoted,
            "secondary_present": cur.execute(
                "SELECT COUNT(*) FROM concept_family_membership WHERE is_primary = 0"
            ).fetchone()[0],
            "concepts_no_primary": cur.execute(
                """SELECT COUNT(*) FROM nodes n WHERE n.type = 'concept'
                   AND NOT EXISTS (SELECT 1 FROM concept_family_membership m
                                   WHERE m.concept_id = n.id AND m.is_primary = 1)"""
            ).fetchone()[0],
            "families_no_concepts": cur.execute(
                """SELECT COUNT(*) FROM concept_families f WHERE f.parent_id IS NOT NULL
                   AND NOT EXISTS (SELECT 1 FROM concept_family_membership m
                                   WHERE m.family_id = f.id)"""
            ).fetchone()[0],
            "families_no_aliases": cur.execute(
                """SELECT COUNT(*) FROM concept_families f
                   WHERE NOT EXISTS (SELECT 1 FROM family_aliases a WHERE a.family_id = f.id)"""
            ).fetchone()[0],
            "concepts_no_aliases": cur.execute(
                """SELECT COUNT(*) FROM nodes n WHERE n.type = 'concept'
                   AND NOT EXISTS (SELECT 1 FROM concept_aliases a WHERE a.concept_id = n.id)"""
            ).fetchone()[0],
        }

        if apply:
            conn.commit()
        else:
            conn.rollback()
        return report
    except Exception:
        conn.rollback()
        raise


def print_report(report: dict, *, apply: bool) -> None:
    print("=" * 64)
    print(f"  taxonomy sync — {'APPLIED' if apply else 'DRY RUN (no writes)'}")
    print("=" * 64)
    print(f"  families upserted ............ {report['families_upserted']}")
    print(f"  concept nodes upserted ....... {report['concepts_upserted']}")
    print(f"  primary memberships created .. {report['primaries_created']}")
    print(f"  primary memberships unchanged  {report['primaries_unchanged']}")
    print(f"  primary memberships moved .... {report['primaries_moved']}")
    for node_id, old, new in report["moves"]:
        print(f"      {node_id}: {old} → {new}")
    print(f"  primaries demoted to secondary {report['primaries_demoted']}")
    print(f"  secondary memberships present  {report['secondary_present']}")
    print("  ── worklists ──")
    print(f"  concepts with no primary family {report['concepts_no_primary']}")
    print(f"  families with no concepts ...... {report['families_no_concepts']}")
    print(f"  families with no aliases ....... {report['families_no_aliases']}")
    print(f"  concepts with no aliases ....... {report['concepts_no_aliases']}")
    if not apply:
        print("\n  (no DB writes — re-run with --apply to commit)")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--db", default=str(DEFAULT_DB),
                   help=f"path to SQLite DB. Default {DEFAULT_DB}.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="summarise what would change without writing (default).")
    mode.add_argument("--apply", action="store_true",
                      help="commit the upserts inside a transaction.")
    args = p.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"DB not found: {db}", file=sys.stderr)
        return 1

    with open(TAXONOMY_TOML, "rb") as f:
        data = tomllib.load(f)
    plan = parse_taxonomy(data)

    conn = sqlite3.connect(str(db))
    conn.isolation_level = None  # explicit transaction control
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        report = sync(conn, plan, apply=args.apply)
    finally:
        conn.close()
    print_report(report, apply=args.apply)
    return 0


if __name__ == "__main__":
    sys.exit(main())
