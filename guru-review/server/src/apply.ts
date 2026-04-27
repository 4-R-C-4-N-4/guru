// Apply transaction — drains review_actions queue into staged_tags or
// staged_edges + edges + nodes, dispatching on target_table. Mirrors
// scripts/review_tags.py and scripts/review_edges.py editorial-overlay
// helpers. The parity harness at tests/parity/ asserts row-content
// equivalence between this and the CLI for the same fixture decisions.
import type Database from 'better-sqlite3';
import type { PreparedStmts } from './db.js';

interface QueuedAction {
  id: number;
  target_id: number;
  target_table: 'staged_tags' | 'staged_edges';
  action: 'accept' | 'reject' | 'skip' | 'reassign' | 'reclassify';
  reassign_to: string | null;
  reclassify_to: string | null;
  reviewer: string;
  client_action_id: string;
  created_at: string;
}

interface StagedTag {
  id: number;
  chunk_id: string;
  concept_id: string;
  score: number;
  justification: string | null;
  is_new_concept: number;
  new_concept_def: string | null;
  status: string;
  model: string | null;
  prompt_version: string | null;
}

interface StagedEdge {
  id: number;
  source_chunk: string;
  target_chunk: string;
  edge_type: 'PARALLELS' | 'CONTRASTS' | 'surface_only' | 'unrelated';
  confidence: number;
  justification: string | null;
  status: string;
  tier: string;
}

export interface ApplyResult {
  applied: number;
  edges_created: number; // upserts on accept/reclassify (verified)
  skipped_already_resolved: number;
  errors: Array<{ action_id: number; client_action_id: string; error: string }>;
}

function nowIso(): string {
  return new Date().toISOString().replace(/\.\d{3}Z$/, 'Z');
}

function pythonTitleCase(s: string): string {
  // Mirror Python str.title(): lowercase rest of word, capitalize first letter
  // of each word. Without the leading toLowerCase(), an uppercase concept_id
  // like "AHURA_MAZDA" would render as "AHURA MAZDA" (web) vs "Ahura Mazda" (CLI).
  return s.toLowerCase().replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}


// ── staged_tags branch (existing behaviour) ────────────────────────────

function applyTagAction(
  stmts: PreparedStmts,
  q: QueuedAction,
  result: ApplyResult,
): boolean {
  const tag = stmts.selectStagedTag.get(q.target_id) as StagedTag | undefined;

  if (!tag || tag.status !== 'pending') {
    stmts.markActionApplied.run(
      `tag was ${tag?.status ?? 'missing'} at apply time`,
      q.id,
    );
    result.skipped_already_resolved++;
    return true;
  }

  switch (q.action) {
    case 'accept': {
      const conceptNodeId = `concept.${tag.concept_id}`;
      const label = pythonTitleCase(tag.concept_id);
      stmts.ensureConceptNode.run(conceptNodeId, label, tag.new_concept_def);
      // Editorial overlay: human accept = verified, full stop.
      stmts.upsertEdge.run(
        tag.chunk_id, conceptNodeId, 'EXPRESSES', 'verified',
        tag.justification ?? '',
      );
      stmts.updateStagedTagStatus.run('accepted', q.reviewer, nowIso(), tag.id);
      result.edges_created++;
      break;
    }
    case 'reject': {
      stmts.deleteEdge.run(tag.chunk_id, `concept.${tag.concept_id}`, 'EXPRESSES');
      stmts.updateStagedTagStatus.run('rejected', q.reviewer, nowIso(), tag.id);
      break;
    }
    case 'reassign': {
      if (!q.reassign_to) {
        throw new Error(`reassign action ${q.id} missing reassign_to`);
      }
      stmts.deleteEdge.run(tag.chunk_id, `concept.${tag.concept_id}`, 'EXPRESSES');
      stmts.updateStagedTagStatus.run('reassigned', q.reviewer, nowIso(), tag.id);
      stmts.updateStagedTagConcept.run(q.reassign_to, tag.id);
      stmts.insertReassignedTag.run(
        tag.chunk_id, q.reassign_to, tag.score,
        `Reassigned from ${tag.concept_id}`,
        tag.model, tag.prompt_version,
      );
      break;
    }
    case 'skip': {
      break;
    }
    default: {
      throw new Error(
        `unknown action for staged_tags: ${q.action} (action ${q.id})`,
      );
    }
  }

  stmts.markActionApplied.run(null, q.id);
  result.applied++;
  return true;
}


// ── staged_edges branch (new) ──────────────────────────────────────────

function applyEdgeAction(
  stmts: PreparedStmts,
  q: QueuedAction,
  result: ApplyResult,
): boolean {
  const edge = stmts.selectStagedEdge.get(q.target_id) as StagedEdge | undefined;

  if (!edge || edge.status !== 'pending') {
    stmts.markActionApplied.run(
      `staged_edge was ${edge?.status ?? 'missing'} at apply time`,
      q.id,
    );
    result.skipped_already_resolved++;
    return true;
  }

  switch (q.action) {
    case 'accept': {
      // Editorial overlay: human accept = verified.
      stmts.upsertEdge.run(
        edge.source_chunk, edge.target_chunk, edge.edge_type,
        'verified', edge.justification ?? '',
      );
      stmts.updateStagedEdgeStatus.run(
        'accepted', 'verified', q.reviewer, nowIso(), edge.id,
      );
      result.edges_created++;
      break;
    }
    case 'reject': {
      stmts.deleteEdge.run(edge.source_chunk, edge.target_chunk, edge.edge_type);
      // Preserve current tier on rejected rows (audit clarity); only status
      // and reviewer/timestamp change.
      stmts.updateStagedEdgeStatus.run(
        'rejected', edge.tier, q.reviewer, nowIso(), edge.id,
      );
      break;
    }
    case 'reclassify': {
      if (!q.reclassify_to) {
        throw new Error(`reclassify action ${q.id} missing reclassify_to`);
      }
      // Always retract the OLD-type edge first.
      stmts.deleteEdge.run(edge.source_chunk, edge.target_chunk, edge.edge_type);

      if (q.reclassify_to === 'PARALLELS' || q.reclassify_to === 'CONTRASTS') {
        // Promote at the new type at tier=verified.
        stmts.upsertEdge.run(
          edge.source_chunk, edge.target_chunk, q.reclassify_to,
          'verified', edge.justification ?? '',
        );
        stmts.updateStagedEdgeStatusType.run(
          'reclassified', q.reclassify_to, 'verified',
          q.reviewer, nowIso(), edge.id,
        );
        result.edges_created++;
      } else {
        // surface_only / unrelated → typed reject. Old edge already deleted;
        // record what the curator classified for audit but write no live edge
        // (the edges.type CHECK forbids these values).
        stmts.updateStagedEdgeStatusType.run(
          'rejected', q.reclassify_to, edge.tier,
          q.reviewer, nowIso(), edge.id,
        );
      }
      break;
    }
    case 'skip': {
      break;
    }
    default: {
      throw new Error(
        `unknown action for staged_edges: ${q.action} (action ${q.id})`,
      );
    }
  }

  stmts.markActionApplied.run(null, q.id);
  result.applied++;
  return true;
}


// ── transaction wrapper ────────────────────────────────────────────────

export function buildApply(rw: Database.Database, stmts: PreparedStmts) {
  const tx = rw.transaction((): ApplyResult => {
    const queued = stmts.selectQueuedActions.all() as QueuedAction[];
    const result: ApplyResult = {
      applied: 0,
      edges_created: 0,
      skipped_already_resolved: 0,
      errors: [],
    };

    for (const q of queued) {
      if (q.target_table === 'staged_tags') {
        applyTagAction(stmts, q, result);
      } else if (q.target_table === 'staged_edges') {
        applyEdgeAction(stmts, q, result);
      } else {
        throw new Error(
          `unknown target_table: ${String(q.target_table)} (action ${q.id})`,
        );
      }
    }

    return result;
  });

  return tx;
}
