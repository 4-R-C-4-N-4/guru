#!/usr/bin/env bash
# Parity harness end-to-end (todo:2cd9f9b5).
#
# Seeds two identical shadow DBs, applies the same decision sequence
# through the CLI's promote_to_expresses and the web's apply transaction,
# then asserts row-content equivalence per design §10.
#
# Exit 0 = parity holds. Exit nonzero = mismatch (diff to stderr).

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/../.." && pwd)"
SHADOW_DIR="$(mktemp -d)"
trap 'rm -rf "$SHADOW_DIR"' EXIT

CLI_DB="$SHADOW_DIR/cli.db"
WEB_DB="$SHADOW_DIR/web.db"
SEED_SQL="$HERE/fixtures/seed.sql"
FIXTURE="$HERE/fixtures/decision_sequence.json"

echo "[parity] seeding shadow DBs in $SHADOW_DIR"
sqlite3 "$CLI_DB" < "$SEED_SQL"
sqlite3 "$WEB_DB" < "$SEED_SQL"

echo "[parity] CLI runner →  $CLI_DB"
python3 "$HERE/runners/run_cli.py" --db "$CLI_DB" --fixture "$FIXTURE"

echo "[parity] WEB runner →  $WEB_DB"
# Compiled by `pnpm -C guru-review/server build`. If missing, build now.
WEB_RUNNER="$PROJECT_ROOT/guru-review/server/dist/parity/web_runner.js"
if [ ! -f "$WEB_RUNNER" ]; then
    echo "[parity] building server (web_runner missing)…" >&2
    ( cd "$PROJECT_ROOT/guru-review" && pnpm -C server build > /dev/null )
fi
node "$WEB_RUNNER" --db "$WEB_DB" --fixture "$FIXTURE" > /dev/null

echo "[parity] comparing shadows…"
python3 "$HERE/compare.py" --cli-db "$CLI_DB" --web-db "$WEB_DB"
