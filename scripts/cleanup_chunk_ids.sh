#!/usr/bin/env bash
# cleanup_chunk_ids.sh — operator wrapper for the chunk_id normalization
# (todo:9ec1dcee). Mirrors the auto_promote_edges.sh + cleanup_orphic_pre_rechunk.sh
# pattern: dry-run by default, --apply takes a labelled snapshot, runs the
# v3_004 SQL migration, runs the corpus TOML backfill, verifies parity.
#
# What this exists to fix:
#   scripts/chunk.py used to build chunk_id from the display-name tradition
#   field ('Christian Mysticism.foo.001'), but on-disk paths are snake_case
#   ('christian_mysticism/foo/...'). resolve_chunk_path papered over the
#   divergence at runtime; this script normalizes the data so the workaround
#   can be removed (todo:234998f8 / C4).
#
# Usage:
#   scripts/cleanup_chunk_ids.sh               # audit only (no writes)
#   scripts/cleanup_chunk_ids.sh --apply       # snapshot + sql + backfill + verify
#   scripts/cleanup_chunk_ids.sh --apply --skip-backfill
#       # corpus already backfilled (re-running, debugging) — skip the python step
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/.." && pwd)"
DB="$PROJECT_ROOT/data/guru.db"
MIGRATION="$HERE/migrations/v3_004_normalize_chunk_ids.sql"
BACKFILL="$HERE/backfill_chunk_ids.py"

APPLY=0
SKIP_BACKFILL=0
for arg in "$@"; do
    case "$arg" in
        --apply)         APPLY=1 ;;
        --skip-backfill) SKIP_BACKFILL=1 ;;
        --help|-h)
            sed -n '2,/^set -/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//;/^set -/d'
            exit 0
            ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

[ -f "$DB" ]          || { echo "live DB not found: $DB" >&2; exit 1; }
[ -f "$MIGRATION" ]   || { echo "migration not found: $MIGRATION" >&2; exit 1; }
[ -f "$BACKFILL" ]    || { echo "backfill script not found: $BACKFILL" >&2; exit 1; }

# ── 1. Audit (always runs) ──────────────────────────────────────────────────

echo "=== Pre-migration audit: chunk_id distribution by form ==="
sqlite3 "$DB" -header -column "
SELECT 'nodes (chunks, display-name)' AS scope,
       COUNT(*) AS n
  FROM nodes
 WHERE type='chunk'
   AND (id GLOB 'Neoplatonism.*' OR id GLOB 'Egyptian.*' OR id GLOB 'Taoism.*'
     OR id GLOB 'Greek Mystery.*' OR id GLOB 'Christian Mysticism.*'
     OR id GLOB 'Zoroastrianism.*' OR id GLOB 'Jewish Mysticism.*'
     OR id GLOB 'Buddhism.*' OR id GLOB 'Mesopotamian.*')
UNION ALL
SELECT 'nodes (chunks, snake_case)',
       COUNT(*)
  FROM nodes
 WHERE type='chunk'
   AND id NOT GLOB '*[A-Z]*' AND id NOT GLOB '* *';
"

# ── 2. Collision audit (must be empty) ──────────────────────────────────────

COLLISIONS=$(sqlite3 "$DB" "
SELECT COUNT(*) FROM nodes
 WHERE type='chunk'
   AND (id GLOB 'Neoplatonism.*' OR id GLOB 'Egyptian.*' OR id GLOB 'Taoism.*'
     OR id GLOB 'Greek Mystery.*' OR id GLOB 'Christian Mysticism.*'
     OR id GLOB 'Zoroastrianism.*' OR id GLOB 'Jewish Mysticism.*'
     OR id GLOB 'Buddhism.*' OR id GLOB 'Mesopotamian.*')
   AND (CASE
       WHEN id GLOB 'Neoplatonism.*'         THEN REPLACE(id, 'Neoplatonism.',         'neoplatonism.')
       WHEN id GLOB 'Egyptian.*'             THEN REPLACE(id, 'Egyptian.',             'egyptian.')
       WHEN id GLOB 'Taoism.*'               THEN REPLACE(id, 'Taoism.',               'taoism.')
       WHEN id GLOB 'Greek Mystery.*'        THEN REPLACE(id, 'Greek Mystery.',        'greek_mystery.')
       WHEN id GLOB 'Christian Mysticism.*'  THEN REPLACE(id, 'Christian Mysticism.',  'christian_mysticism.')
       WHEN id GLOB 'Zoroastrianism.*'       THEN REPLACE(id, 'Zoroastrianism.',       'zoroastrianism.')
       WHEN id GLOB 'Jewish Mysticism.*'     THEN REPLACE(id, 'Jewish Mysticism.',     'jewish_mysticism.')
       WHEN id GLOB 'Buddhism.*'             THEN REPLACE(id, 'Buddhism.',             'buddhism.')
       WHEN id GLOB 'Mesopotamian.*'         THEN REPLACE(id, 'Mesopotamian.',         'mesopotamian.')
   END) IN (SELECT id FROM nodes WHERE type='chunk');
")
if [ "$COLLISIONS" -ne 0 ]; then
    echo
    echo "ABORT: $COLLISIONS chunk_id collision(s) detected." >&2
    echo "The following display-name chunk_ids would conflict with existing" >&2
    echo "snake_case rows on rewrite:" >&2
    sqlite3 "$DB" -header -column "
    SELECT id AS would_collide
      FROM nodes
     WHERE type='chunk'
       AND (id GLOB 'Neoplatonism.*' OR id GLOB 'Egyptian.*' OR id GLOB 'Taoism.*'
         OR id GLOB 'Greek Mystery.*' OR id GLOB 'Christian Mysticism.*'
         OR id GLOB 'Zoroastrianism.*' OR id GLOB 'Jewish Mysticism.*'
         OR id GLOB 'Buddhism.*' OR id GLOB 'Mesopotamian.*')
       AND (CASE
           WHEN id GLOB 'Neoplatonism.*'         THEN REPLACE(id, 'Neoplatonism.',         'neoplatonism.')
           WHEN id GLOB 'Egyptian.*'             THEN REPLACE(id, 'Egyptian.',             'egyptian.')
           WHEN id GLOB 'Taoism.*'               THEN REPLACE(id, 'Taoism.',               'taoism.')
           WHEN id GLOB 'Greek Mystery.*'        THEN REPLACE(id, 'Greek Mystery.',        'greek_mystery.')
           WHEN id GLOB 'Christian Mysticism.*'  THEN REPLACE(id, 'Christian Mysticism.',  'christian_mysticism.')
           WHEN id GLOB 'Zoroastrianism.*'       THEN REPLACE(id, 'Zoroastrianism.',       'zoroastrianism.')
           WHEN id GLOB 'Jewish Mysticism.*'     THEN REPLACE(id, 'Jewish Mysticism.',     'jewish_mysticism.')
           WHEN id GLOB 'Buddhism.*'             THEN REPLACE(id, 'Buddhism.',             'buddhism.')
           WHEN id GLOB 'Mesopotamian.*'         THEN REPLACE(id, 'Mesopotamian.',         'mesopotamian.')
       END) IN (SELECT id FROM nodes WHERE type='chunk');" >&2
    echo >&2
    echo "Reconcile manually (decide which form to keep, drop the other) and re-run." >&2
    exit 1
fi

if [ "$APPLY" -eq 0 ]; then
    echo
    echo "(audit only — re-run with --apply to take a snapshot, run the v3_004"
    echo " migration, and rewrite corpus TOML files)"
    exit 0
fi

# ── 3. Snapshot ─────────────────────────────────────────────────────────────

mkdir -p "$HOME/guru-backups"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="$HOME/guru-backups/guru-${TS}-pre-chunk-id-normalize.db"
echo
echo "[snapshot] taking $SNAP"
sqlite3 "$DB" ".backup '$SNAP'"
INTEGRITY="$(sqlite3 "$SNAP" "PRAGMA integrity_check" | head -1)"
[ "$INTEGRITY" = "ok" ] || {
    echo "ABORT: snapshot integrity check failed: $INTEGRITY" >&2
    exit 1
}
echo "[snapshot] integrity_check ok"

# Manifest with row counts
sqlite3 "$DB" "
SELECT 'nodes (chunks)',     COUNT(*) FROM nodes WHERE type='chunk' UNION ALL
SELECT 'edges',              COUNT(*) FROM edges UNION ALL
SELECT 'edges (verified)',   COUNT(*) FROM edges WHERE tier='verified' UNION ALL
SELECT 'chunk_embeddings',   COUNT(*) FROM chunk_embeddings UNION ALL
SELECT 'staged_tags',        COUNT(*) FROM staged_tags UNION ALL
SELECT 'staged_edges',       COUNT(*) FROM staged_edges UNION ALL
SELECT 'tagging_progress',   COUNT(*) FROM tagging_progress;
" > "$SNAP.manifest.txt"

# ── 4. Apply migration ──────────────────────────────────────────────────────

echo
echo "[migration] applying $MIGRATION"
sqlite3 "$DB" < "$MIGRATION"

# Hard verification: zero residual display-name refs anywhere
RESIDUAL=$(sqlite3 "$DB" "
SELECT COALESCE(SUM(n), 0) FROM (
    SELECT COUNT(*) AS n FROM nodes WHERE type='chunk' AND (id GLOB '* *' OR id GLOB '*[A-Z]*')
    UNION ALL SELECT COUNT(*) FROM edges WHERE source_id GLOB '* *' OR (source_id GLOB '*[A-Z]*' AND source_id NOT GLOB 'concept.*')
    UNION ALL SELECT COUNT(*) FROM edges WHERE target_id GLOB '* *' OR (target_id GLOB '*[A-Z]*' AND target_id NOT GLOB 'concept.*')
    UNION ALL SELECT COUNT(*) FROM chunk_embeddings WHERE chunk_id GLOB '* *' OR chunk_id GLOB '*[A-Z]*'
    UNION ALL SELECT COUNT(*) FROM staged_tags WHERE chunk_id GLOB '* *' OR chunk_id GLOB '*[A-Z]*'
    UNION ALL SELECT COUNT(*) FROM staged_edges WHERE source_chunk GLOB '* *' OR source_chunk GLOB '*[A-Z]*'
    UNION ALL SELECT COUNT(*) FROM staged_edges WHERE target_chunk GLOB '* *' OR target_chunk GLOB '*[A-Z]*'
    UNION ALL SELECT COUNT(*) FROM tagging_progress WHERE chunk_id GLOB '* *' OR chunk_id GLOB '*[A-Z]*'
    UNION ALL SELECT COUNT(*) FROM staged_concepts WHERE motivating_chunk GLOB '* *' OR motivating_chunk GLOB '*[A-Z]*'
);
")
if [ "$RESIDUAL" -ne 0 ]; then
    echo "ABORT: $RESIDUAL display-name refs still present after migration." >&2
    echo "Snapshot at $SNAP — restore with: cp $SNAP $DB" >&2
    exit 1
fi
echo "[migration] residual display-name refs: 0"

FK_VIOLATIONS=$(sqlite3 "$DB" "PRAGMA foreign_key_check;" | wc -l)
[ "$FK_VIOLATIONS" -eq 0 ] || {
    echo "ABORT: $FK_VIOLATIONS FK violations after migration." >&2
    sqlite3 "$DB" "PRAGMA foreign_key_check;" | head -10 >&2
    echo "Snapshot at $SNAP — restore with: cp $SNAP $DB" >&2
    exit 1
}
echo "[migration] foreign_key_check: ok"

# ── 5. Run corpus TOML backfill ─────────────────────────────────────────────

if [ "$SKIP_BACKFILL" -eq 1 ]; then
    echo
    echo "[backfill] skipped per --skip-backfill"
else
    echo
    echo "[backfill] python3 $BACKFILL --apply"
    python3 "$BACKFILL" --apply
fi

# ── 6. Verify corpus/DB parity ──────────────────────────────────────────────

echo
echo "[verify] sampling chunk_ids — corpus TOML should match DB nodes"
PARITY_FAIL=0
SAMPLES=$(sqlite3 "$DB" "SELECT id FROM nodes WHERE type='chunk' ORDER BY RANDOM() LIMIT 5;")
while IFS= read -r cid; do
    [ -n "$cid" ] || continue
    # chunk_id format: '<tradition>.<text>.<seq>' — convert to corpus path.
    trad="${cid%%.*}"
    rest="${cid#*.}"
    text="${rest%.*}"
    seq="${rest##*.}"
    path="$PROJECT_ROOT/corpus/$trad/$text/chunks/$seq.toml"
    if [ -f "$path" ]; then
        echo "  ✓ $cid → $path"
    else
        echo "  ✗ $cid → $path (NOT FOUND)" >&2
        PARITY_FAIL=$((PARITY_FAIL + 1))
    fi
done <<< "$SAMPLES"

if [ "$PARITY_FAIL" -gt 0 ]; then
    echo "ABORT: $PARITY_FAIL/5 sampled chunk_ids have no matching corpus TOML." >&2
    echo "Snapshot at $SNAP — restore with: cp $SNAP $DB" >&2
    exit 1
fi

echo
echo "[done] Snapshot: $SNAP"
echo "       Manifest: $SNAP.manifest.txt"
echo "       Live DB and corpus are now consistent on snake_case chunk_ids."
echo "       Next: drop the resolve_chunk_path fallback (todo:234998f8 / C4)."
