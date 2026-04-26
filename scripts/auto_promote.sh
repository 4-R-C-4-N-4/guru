#!/usr/bin/env bash
# auto_promote.sh — wrapper around scripts/auto_promote.py.
#
# Dry-run by default. With --apply: takes a labeled snapshot first
# (via the SQLite online backup API + integrity_check), then runs the
# Python script with --apply. Mirrors scripts/cleanup_dupes.sh pattern.
#
#   scripts/auto_promote.sh                    # dry-run, --score 3 default
#   scripts/auto_promote.sh --score 2          # dry-run, lower floor
#   scripts/auto_promote.sh --apply            # snapshot + commit (score 3)
#   scripts/auto_promote.sh --score 2 --apply  # snapshot + commit (score >= 2)

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/.." && pwd)"
DB="$PROJECT_ROOT/data/guru.db"
PY="$HERE/auto_promote.py"

# Pass-through args, but intercept --apply so we can take the snapshot first.
APPLY=0
PASS_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        --help|-h) python3 "$PY" --help; exit 0 ;;
        *) PASS_ARGS+=("$arg") ;;
    esac
done

[ -f "$DB" ] || { echo "live DB not found: $DB" >&2; exit 1; }
[ -f "$PY" ] || { echo "python script not found: $PY" >&2; exit 1; }

if [ "$APPLY" -eq 0 ]; then
    echo "=== DRY RUN ==="
    python3 "$PY" --db "$DB" "${PASS_ARGS[@]}"
    echo
    echo "(dry-run only — re-run with --apply to commit)"
    exit 0
fi

# ---- apply path ----
mkdir -p "$HOME/guru-backups"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="$HOME/guru-backups/guru-${TS}-pre-autopromote.db"
echo "[snapshot] taking $SNAP"
sqlite3 "$DB" ".backup '$SNAP'"

INTEGRITY="$(sqlite3 "$SNAP" "PRAGMA integrity_check" | head -1)"
[ "$INTEGRITY" = "ok" ] || { echo "ABORT: snapshot integrity check failed: $INTEGRITY" >&2; exit 1; }
echo "[snapshot] integrity_check ok"

# Manifest with row counts (matches the ~/guru-backups discipline)
sqlite3 "$DB" "
SELECT 'staged_tags total',         COUNT(*) FROM staged_tags UNION ALL
SELECT 'staged_tags pending',       COUNT(*) FROM staged_tags WHERE status='pending' UNION ALL
SELECT 'edges total',               COUNT(*) FROM edges UNION ALL
SELECT 'edges EXPRESSES verified',  COUNT(*) FROM edges WHERE type='EXPRESSES' AND tier='verified' UNION ALL
SELECT 'edges EXPRESSES proposed',  COUNT(*) FROM edges WHERE type='EXPRESSES' AND tier='proposed' UNION ALL
SELECT 'edges EXPRESSES inferred',  COUNT(*) FROM edges WHERE type='EXPRESSES' AND tier='inferred';
" > "$SNAP.manifest.txt"

echo "[apply] running auto_promote.py with --apply"
python3 "$PY" --db "$DB" --apply "${PASS_ARGS[@]}"
echo "[apply] done. Snapshot: $SNAP"
