#!/usr/bin/env bash
# scripts/local_load_test.sh — load the v2 export artifact into a throwaway
# pgvector container and smoke-test it as the app role.
#
# Catches artifact-side regressions before they hit prod (ALTER SCHEMA syntax,
# missing GRANTs, schema-prefix bugs, etc.). The container survives the
# script so you can point local guru-web at it:
#
#     DATABASE_URL=postgres://guru:test@localhost:5433/guru npm run dev
#
# Re-running the script tears down the previous container and starts fresh.

set -euo pipefail

CONTAINER=${CONTAINER:-guru-pg-test}
PORT=${PORT:-5433}
IMAGE=${IMAGE:-docker.io/pgvector/pgvector:pg17}
APP_ROLE=guru                   # must match scripts/export.py:APP_ROLE
APP_DB=guru
PASSWORD=test                   # local-only; the container is never exposed

cd "$(dirname "$0")/.."

command -v podman >/dev/null \
  || { echo "podman not found. Install with: sudo pacman -S podman" >&2; exit 1; }

echo "==> [1/5] tearing down any prior $CONTAINER"
podman rm -f "$CONTAINER" >/dev/null 2>&1 || true

echo "==> [2/5] starting $CONTAINER on :$PORT"
podman run -d --name "$CONTAINER" \
  -e POSTGRES_PASSWORD="$PASSWORD" \
  -p "$PORT:5432" \
  "$IMAGE" >/dev/null

for _ in $(seq 1 30); do
  podman exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1 && break
  sleep 1
done
podman exec "$CONTAINER" pg_isready -U postgres >/dev/null 2>&1 \
  || { echo "postgres did not become ready within 30s" >&2; exit 1; }

echo "==> [3/5] creating role + database"
podman exec -i "$CONTAINER" psql -U postgres -v ON_ERROR_STOP=1 <<SQL
CREATE ROLE $APP_ROLE LOGIN PASSWORD '$PASSWORD';
CREATE DATABASE $APP_DB OWNER $APP_ROLE;
SQL

echo "==> [4/5] running scripts/export.py"
python scripts/export.py

echo "==> [5/5] loading artifact (as superuser, like prod)"
gunzip -c export/guru-corpus.sql.gz \
  | podman exec -i "$CONTAINER" psql -U postgres -d "$APP_DB" -v ON_ERROR_STOP=1

echo
echo "==> smoke test as $APP_ROLE (proves GRANTs work)"
podman exec -e PGPASSWORD="$PASSWORD" -i "$CONTAINER" \
  psql -h localhost -U "$APP_ROLE" -d "$APP_DB" -v ON_ERROR_STOP=1 <<'SQL'
\pset border 1
SELECT key, value FROM corpus.corpus_metadata ORDER BY key;
SELECT 'traditions' AS rel, COUNT(*) FROM corpus.traditions UNION ALL
SELECT 'texts',            COUNT(*) FROM corpus.texts       UNION ALL
SELECT 'concepts',         COUNT(*) FROM corpus.concepts    UNION ALL
SELECT 'chunks',           COUNT(*) FROM corpus.chunks      UNION ALL
SELECT 'edges',            COUNT(*) FROM corpus.edges;
-- exercise the HNSW index path
SELECT id FROM corpus.chunks ORDER BY embedding <=> (SELECT embedding FROM corpus.chunks LIMIT 1) LIMIT 3;
SQL

echo
echo "load OK. container left running on :$PORT"
echo "  DATABASE_URL=postgres://$APP_ROLE:$PASSWORD@localhost:$PORT/$APP_DB"
echo "  podman stop $CONTAINER   # tear down"
