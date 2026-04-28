#!/usr/bin/env bash
# cleanup_orphic_pre_rechunk.sh — pre-rechunk audit + safe-state preparation
# for the greek_mystery/orphic-hymns text.
#
# This script was originally specified to DELETE Orphic-keyed rows from
# nodes / edges / staged_tags / staged_edges / chunk_embeddings on the
# assumption that the chunker fix (todo:dc8a8e00) would change the
# chunk_id space. In practice, the chunker fix preserves chunk_ids
# (page-as-chunk → 141 raw pages → 141 chunks → identical NN numbering),
# so the heavy cleanup is unnecessary. See analysis on todo:d47747c4.
#
# What IS needed: re-embed. Old embeddings were computed against bodies
# polluted with sacred-texts.com navigation cruft ('Sacred Texts Classics
# Index Previous Next ...'). New chunk bodies are clean — embeddings need
# to be regenerated against the clean text.
#
# This script keeps a structured audit + snapshot to leave a paper trail.
# The actual re-embed is delegated to embed_corpus.py --reindex (which
# already does the right thing with --tradition / --text filters).
#
# Usage:
#   scripts/cleanup_orphic_pre_rechunk.sh                  # snapshot + audit (no writes)
#   scripts/cleanup_orphic_pre_rechunk.sh --apply          # snapshot + reindex orphic embeddings
#   scripts/cleanup_orphic_pre_rechunk.sh --apply --force-reset-staged
#       # also reset Orphic staged_edges back to status='pending' so they
#       # can be re-proposed against the new (clean) embeddings.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/.." && pwd)"
DB="$PROJECT_ROOT/data/guru.db"

APPLY=0
RESET_STAGED=0
for arg in "$@"; do
    case "$arg" in
        --apply) APPLY=1 ;;
        --force-reset-staged) RESET_STAGED=1 ;;
        --help|-h)
            sed -n '2,/^$/p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *) echo "unknown flag: $arg" >&2; exit 2 ;;
    esac
done

[ -f "$DB" ] || { echo "live DB not found: $DB" >&2; exit 1; }

# ---- audit (always runs) ----

echo "=== Pre-rechunk audit: orphic-hymns ==="
sqlite3 "$DB" -header -column "
SELECT 'nodes (chunks)'        AS scope, COUNT(*) AS n FROM nodes
    WHERE id LIKE 'Greek Mystery.orphic-hymns.%' AND type='chunk' UNION ALL
SELECT 'embeddings',                    COUNT(*) FROM chunk_embeddings
    WHERE chunk_id LIKE 'Greek Mystery.orphic-hymns.%' UNION ALL
SELECT 'edges (source side)',           COUNT(*) FROM edges
    WHERE source_id LIKE 'Greek Mystery.orphic-hymns.%' UNION ALL
SELECT 'edges (target side)',           COUNT(*) FROM edges
    WHERE target_id LIKE 'Greek Mystery.orphic-hymns.%' UNION ALL
SELECT '  ↳ verified',                  COUNT(*) FROM edges
    WHERE (source_id LIKE 'Greek Mystery.orphic-hymns.%'
        OR target_id LIKE 'Greek Mystery.orphic-hymns.%') AND tier='verified' UNION ALL
SELECT '  ↳ proposed',                  COUNT(*) FROM edges
    WHERE (source_id LIKE 'Greek Mystery.orphic-hymns.%'
        OR target_id LIKE 'Greek Mystery.orphic-hymns.%') AND tier='proposed' UNION ALL
SELECT '  ↳ proposed [auto]',           COUNT(*) FROM edges
    WHERE (source_id LIKE 'Greek Mystery.orphic-hymns.%'
        OR target_id LIKE 'Greek Mystery.orphic-hymns.%')
        AND tier='proposed' AND justification LIKE '[auto]%' UNION ALL
SELECT 'staged_tags',                   COUNT(*) FROM staged_tags
    WHERE chunk_id LIKE 'Greek Mystery.orphic-hymns.%' UNION ALL
SELECT 'staged_edges',                  COUNT(*) FROM staged_edges
    WHERE source_chunk LIKE 'Greek Mystery.orphic-hymns.%'
       OR target_chunk LIKE 'Greek Mystery.orphic-hymns.%';
"

if [ "$APPLY" -eq 0 ]; then
    echo
    echo "(audit only — re-run with --apply to take a snapshot and reindex Orphic embeddings)"
    exit 0
fi

# ---- apply path ----

mkdir -p "$HOME/guru-backups"
TS="$(date -u +%Y%m%dT%H%M%SZ)"
SNAP="$HOME/guru-backups/guru-${TS}-pre-orphic-rechunk.db"
echo
echo "[snapshot] taking $SNAP"
sqlite3 "$DB" ".backup '$SNAP'"
INTEGRITY="$(sqlite3 "$SNAP" "PRAGMA integrity_check" | head -1)"
[ "$INTEGRITY" = "ok" ] || { echo "ABORT: snapshot integrity check failed: $INTEGRITY" >&2; exit 1; }
echo "[snapshot] integrity_check ok"

# Reset Orphic staged_edges to pending if requested (so they re-qualify
# for auto_promote_edges against the cleaner embeddings).
if [ "$RESET_STAGED" -eq 1 ]; then
    echo
    echo "[reset-staged] resetting orphic staged_edges to status='pending'"
    sqlite3 "$DB" "
        BEGIN;
        UPDATE staged_edges
           SET status='pending',
               reviewed_by=NULL,
               reviewed_at=NULL
         WHERE (source_chunk LIKE 'Greek Mystery.orphic-hymns.%'
            OR  target_chunk LIKE 'Greek Mystery.orphic-hymns.%')
           AND status != 'pending';
        SELECT 'staged_edges reset to pending', changes();
        COMMIT;
    "
fi

# Re-embed Orphic chunks against the new clean bodies. embed_corpus.py
# uses INSERT OR REPLACE keyed on chunk_id, so old embedding rows are
# overwritten. --tradition + --text scopes the work.
echo
echo "[reindex] python3 scripts/embed_corpus.py --reindex --tradition greek_mystery --text orphic-hymns"
python3 "$HERE/embed_corpus.py" --reindex --tradition greek_mystery --text orphic-hymns
echo
echo "[done] Snapshot: $SNAP"
echo "       Re-run validate_index: python3 scripts/validate_index.py"
