#!/usr/bin/env bash
# backup_db.sh — quick labeled snapshot of data/guru.db.
#
# Usage:
#   scripts/backup_db.sh                # label defaults to "manual"
#   scripts/backup_db.sh pre-experiment # custom label
#
# Writes:
#   ~/guru-backups/guru-<ts>-<label>.db          (online-backup snapshot)
#   ~/guru-backups/guru-<ts>-<label>.db.manifest.txt
#
# Refuses to proceed if the snapshot fails PRAGMA integrity_check.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/.." && pwd)"
DB="$PROJECT_ROOT/data/guru.db"

LABEL="${1:-manual}"
# Sanitize: only alnum + dash, so the resulting filename is safe.
LABEL="$(echo "$LABEL" | tr -c '[:alnum:]-' '-' | sed 's/--*/-/g; s/^-//; s/-$//')"
[ -n "$LABEL" ] || { echo "label cannot be empty after sanitization" >&2; exit 1; }

[ -f "$DB" ] || { echo "DB not found: $DB" >&2; exit 1; }

mkdir -p "$HOME/guru-backups"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="$HOME/guru-backups/guru-${TS}-${LABEL}.db"

echo "[backup] $DB → $SNAP"
sqlite3 "$DB" ".backup '$SNAP'"

INTEGRITY="$(sqlite3 "$SNAP" "PRAGMA integrity_check" | head -1)"
if [ "$INTEGRITY" != "ok" ]; then
    echo "ABORT: snapshot integrity check returned: $INTEGRITY" >&2
    rm -f "$SNAP" "$SNAP-shm" "$SNAP-wal"
    exit 1
fi
echo "[backup] integrity_check ok"

# Manifest: row counts for the canary discipline (~/guru-backups).
sqlite3 "$DB" "
SELECT 'staged_tags total',         COUNT(*) FROM staged_tags UNION ALL
SELECT 'staged_tags pending',       COUNT(*) FROM staged_tags WHERE status='pending' UNION ALL
SELECT 'staged_tags accepted',      COUNT(*) FROM staged_tags WHERE status='accepted' UNION ALL
SELECT 'staged_tags rejected',      COUNT(*) FROM staged_tags WHERE status='rejected' UNION ALL
SELECT 'staged_tags reassigned',    COUNT(*) FROM staged_tags WHERE status='reassigned' UNION ALL
SELECT 'edges total',               COUNT(*) FROM edges UNION ALL
SELECT 'edges EXPRESSES verified',  COUNT(*) FROM edges WHERE type='EXPRESSES' AND tier='verified' UNION ALL
SELECT 'edges EXPRESSES proposed',  COUNT(*) FROM edges WHERE type='EXPRESSES' AND tier='proposed' UNION ALL
SELECT 'edges EXPRESSES inferred',  COUNT(*) FROM edges WHERE type='EXPRESSES' AND tier='inferred' UNION ALL
SELECT 'nodes total',               COUNT(*) FROM nodes UNION ALL
SELECT 'nodes concept',             COUNT(*) FROM nodes WHERE type='concept' UNION ALL
SELECT 'nodes chunk',               COUNT(*) FROM nodes WHERE type='chunk';
" > "$SNAP.manifest.txt"

SIZE="$(du -h "$SNAP" | cut -f1)"
echo "[backup] $SIZE"
echo "[backup] manifest:  $SNAP.manifest.txt"
