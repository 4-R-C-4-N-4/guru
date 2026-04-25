// Apply transaction — drains review_actions queue into staged_tags + edges + nodes.
// Mirrors scripts/review_tags.py:promote_to_expresses exactly. The parity
// harness at tests/parity/ asserts row-content equivalence between this and
// the CLI for the same fixture decision sequence.
import type Database from 'better-sqlite3';
import type { PreparedStmts } from './db.js';

interface QueuedAction {
  id: number;
  staged_tag_id: number;
  action: 'accept' | 'reject' | 'skip' | 'reassign';
  reassign_to: string | null;
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
}

export interface ApplyResult {
  applied: number;
  edges_created: number; // counts inserts/upserts on edges (accepts only)
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
      const tag = stmts.selectStagedTag.get(q.staged_tag_id) as StagedTag | undefined;

      // Re-check status — if CLI got there first, no-op (audit-trail preserved).
      if (!tag || tag.status !== 'pending') {
        stmts.markActionApplied.run(
          `tag was ${tag?.status ?? 'missing'} at apply time`,
          q.id,
        );
        result.skipped_already_resolved++;
        continue;
      }

      switch (q.action) {
        case 'accept': {
          const conceptNodeId = `concept.${tag.concept_id}`;
          const label = pythonTitleCase(tag.concept_id);
          // COALESCE in the prepared stmt preserves any pre-existing definition
          // (taxonomy-seeded concepts safe). Pass new_concept_def regardless of
          // is_new_concept — for is_new_concept=0 it's null, harmless.
          stmts.ensureConceptNode.run(conceptNodeId, label, tag.new_concept_def);
          const tier = tag.score >= 2 ? 'verified' : 'proposed';
          stmts.insertOrUpdateEdge.run(
            tag.chunk_id,
            conceptNodeId,
            tier,
            tag.justification ?? '',
          );
          stmts.updateStagedTagStatus.run('accepted', q.reviewer, nowIso(), tag.id);
          result.edges_created++;
          break;
        }
        case 'reject': {
          stmts.updateStagedTagStatus.run('rejected', q.reviewer, nowIso(), tag.id);
          break;
        }
        case 'reassign': {
          if (!q.reassign_to) {
            throw new Error(`reassign action ${q.id} missing reassign_to`);
          }
          stmts.updateStagedTagStatus.run('reassigned', q.reviewer, nowIso(), tag.id);
          stmts.updateStagedTagConcept.run(q.reassign_to, tag.id);
          stmts.insertReassignedTag.run(
            tag.chunk_id,
            q.reassign_to,
            tag.score,
            `Reassigned from ${tag.concept_id}`,
          );
          break;
        }
        case 'skip': {
          // No staged_tags write — close the action only.
          break;
        }
        default: {
          const exhaustive: never = q.action;
          throw new Error(`unknown action: ${String(exhaustive)}`);
        }
      }

      stmts.markActionApplied.run(null, q.id);
      result.applied++;
    }

    return result;
  });

  return tx;
}
