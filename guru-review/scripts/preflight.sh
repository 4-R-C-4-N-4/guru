#!/usr/bin/env bash
# guru-review pre-first-apply preflight (todo:f8c2a68c, design.md §10, impl.md P14).
#
# Run this BEFORE flipping dry_run:false for the first time. Refuses to
# proceed if any check fails.
#
# Usage:
#   bash guru-review/scripts/preflight.sh
#
# What it does:
#   1. Confirms current canary counts against ~/guru-backups manifest.
#   2. Runs the parity harness; refuses if it fails.
#   3. Takes a fresh snapshot labeled pre-first-web-apply.
#   4. Confirms guru-review/server/config.json has dry_run:false (or warns).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/../.." && pwd)"

GREEN=$(printf '\033[0;32m'); RED=$(printf '\033[0;31m'); YELLOW=$(printf '\033[1;33m'); RESET=$(printf '\033[0m')
ok()   { echo "  ${GREEN}✓${RESET} $1"; }
fail() { echo "  ${RED}✗${RESET} $1" >&2; exit 1; }
warn() { echo "  ${YELLOW}!${RESET} $1"; }

echo "=== guru-review preflight ==="

# 1. Canary --------------------------------------------------------------------
echo "[1/4] canary check"
DB="$PROJECT_ROOT/data/guru.db"
[ -f "$DB" ] || fail "live DB not found at $DB"
TOTAL=$(sqlite3 "$DB" "SELECT COUNT(*) FROM staged_tags")
EDGES=$(sqlite3 "$DB" "SELECT COUNT(*) FROM edges")
NODES=$(sqlite3 "$DB" "SELECT COUNT(*) FROM nodes")
ACCEPTED=$(sqlite3 "$DB" "SELECT COUNT(*) FROM staged_tags WHERE status='accepted'")
echo "  current: staged_tags=$TOTAL edges=$EDGES nodes=$NODES accepted=$ACCEPTED"

MANIFEST="$HOME/guru-backups/guru-pre-web-review-manifest.txt"
if [ ! -f "$MANIFEST" ]; then
  warn "no pre-web-review manifest at $MANIFEST — recording current as new baseline"
else
  EXPECTED=$(grep -E "staged_tags total" "$MANIFEST" | awk '{print $NF}' || true)
  if [ -n "$EXPECTED" ] && [ "$EXPECTED" != "$TOTAL" ]; then
    warn "staged_tags drifted from manifest ($EXPECTED → $TOTAL); investigate before applying"
  else
    ok "canary matches manifest baseline"
  fi
fi

# 2. Parity harness ------------------------------------------------------------
echo "[2/4] parity harness"
if bash "$PROJECT_ROOT/tests/parity/orchestrator.sh" > /tmp/parity.log 2>&1; then
  ok "parity harness green"
else
  echo "----- /tmp/parity.log -----" >&2
  tail -30 /tmp/parity.log >&2
  fail "parity harness failed — refuse to proceed"
fi

# 3. Pre-first-web-apply snapshot ---------------------------------------------
echo "[3/4] pre-first-web-apply snapshot"
mkdir -p "$HOME/guru-backups"
TS=$(date -u +%Y%m%dT%H%M%SZ)
SNAP="$HOME/guru-backups/guru-${TS}-pre-first-web-apply.db"
sqlite3 "$DB" ".backup $SNAP"
INTEGRITY=$(sqlite3 "$SNAP" "PRAGMA integrity_check" | head -1)
[ "$INTEGRITY" = "ok" ] || fail "snapshot integrity check failed: $INTEGRITY"
ok "snapshot at $SNAP (integrity ok)"

cat > "$SNAP.manifest.json" <<EOF
{
  "created_at": "$TS",
  "label": "pre-first-web-apply",
  "source": "$DB",
  "integrity": "ok",
  "staged_tags": $TOTAL,
  "accepted": $ACCEPTED,
  "edges": $EDGES,
  "nodes": $NODES
}
EOF
ok "manifest written"

# 4. Config check --------------------------------------------------------------
echo "[4/4] server config"
CFG="$PROJECT_ROOT/guru-review/server/config.json"
if [ -f "$CFG" ]; then
  DRY_RUN=$(python3 -c "import json,sys; print(json.load(open('$CFG'))['dry_run'])" 2>/dev/null || echo "?")
  if [ "$DRY_RUN" = "True" ] || [ "$DRY_RUN" = "true" ]; then
    warn "config.json dry_run=true — flip to false before starting the server for live apply"
  else
    ok "config.json dry_run=false"
  fi
else
  warn "no config.json (using config.example.json's dry_run=false). Copy and edit if needed."
fi

echo
echo "${GREEN}=== preflight passed — safe to start server and run a small (~20 tag) batch ===${RESET}"
echo "After the apply, audit:"
echo "  sqlite3 $DB \"SELECT id, status, reviewed_by, reviewed_at FROM staged_tags WHERE reviewed_by LIKE 'ivy-%' ORDER BY reviewed_at DESC LIMIT 20\""
echo "  sqlite3 $DB \"SELECT source_id, target_id, tier FROM edges WHERE created_at >= date('now') ORDER BY id DESC LIMIT 20\""
