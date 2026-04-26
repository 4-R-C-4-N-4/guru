#!/usr/bin/env bash
# cleanup_dupes.sh — wrapper around scripts/cleanup_dupes.sql.
#
# Dry-run by default. With --apply: takes a labeled snapshot first, then
# runs the SQL with the trailing ROLLBACK swapped for COMMIT.
#
#   scripts/cleanup_dupes.sh             # dry-run (always safe)
#   scripts/cleanup_dupes.sh --apply     # snapshot + commit

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/.." && pwd)"
DB="$PROJECT_ROOT/data/guru.db"
SQL="$HERE/cleanup_dupes.sql"

APPLY=0
case "${1:-}" in
    --apply)   APPLY=1 ;;
    --help|-h) echo "usage: $0 [--apply]"; exit 0 ;;
    "")        ;;
    *)         echo "unknown flag: $1" >&2; exit 2 ;;
esac

[ -f "$DB" ]  || { echo "live DB not found: $DB" >&2; exit 1; }
[ -f "$SQL" ] || { echo "SQL script not found: $SQL" >&2; exit 1; }

if [ "$APPLY" -eq 0 ]; then
    echo "=== DRY RUN ==="
    sqlite3 "$DB" < "$SQL"
    echo
    echo "(dry-run only — re-run with --apply to commit)"
    exit 0
fi

# ---- apply path ----
mkdir -p "$HOME/guru-backups"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="$HOME/guru-backups/guru-${TS}-pre-dedupe.db"
echo "[snapshot] taking $SNAP"
sqlite3 "$DB" ".backup '$SNAP'"

INTEGRITY="$(sqlite3 "$SNAP" "PRAGMA integrity_check" | head -1)"
[ "$INTEGRITY" = "ok" ] || { echo "ABORT: snapshot integrity check failed: $INTEGRITY" >&2; exit 1; }
echo "[snapshot] integrity_check ok"

# Manifest (matches the ~/guru-backups discipline)
sqlite3 "$DB" "
SELECT 'staged_tags total',         COUNT(*) FROM staged_tags UNION ALL
SELECT 'staged_tags pending',       COUNT(*) FROM staged_tags WHERE status='pending' UNION ALL
SELECT 'edges',                     COUNT(*) FROM edges UNION ALL
SELECT 'nodes',                     COUNT(*) FROM nodes;
" > "$SNAP.manifest.txt"

echo "[apply] running cleanup_dupes.sql with COMMIT"
sed 's/^ROLLBACK;$/COMMIT;/' "$SQL" | sqlite3 "$DB"
echo "[apply] done. Snapshot: $SNAP"
