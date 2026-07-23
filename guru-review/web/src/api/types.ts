export interface PendingTag {
  target_id: number;
  concept_id: string;
  concept_label: string;
  concept_def: string;
  score: 0 | 1 | 2 | 3;
  justification: string;
  is_new_concept: boolean;
  new_concept_def: string | null;
}

export interface Chunk {
  chunk_id: string;
  tradition_id: string;
  section_label: string;
  text_id: string | null;
  body: string;
  pending_tags: PendingTag[];
}

export interface ChunksResponse {
  chunks: Chunk[];
  next_cursor: string | null;
  pending_chunks_in_filter: number;
  pending_tags_in_filter: number;
}

export interface ConceptDef {
  node_id: string;
  concept_id: string;
  label: string;
  definition: string | null;
}

// ── edge review (staged_edges) ───────────────────────────────────────

export type EdgeType = 'PARALLELS' | 'CONTRASTS' | 'surface_only' | 'unrelated';

export interface EdgeChunk {
  chunk_id: string;
  tradition_id: string;
  section_label: string;
  text_id: string | null;
  body: string;
}

export interface PendingEdge {
  target_id: number;
  edge_type: EdgeType;
  confidence: number;
  justification: string;
  tier: string;
  a: EdgeChunk;
  b: EdgeChunk;
}

export interface EdgesResponse {
  edges: PendingEdge[];
  next_cursor: number | null;
  pending_edges_in_filter: number;
}

export interface EdgeFilterParams {
  edge_type?: 'PARALLELS' | 'CONTRASTS';
  min_confidence?: number;
  tradition_a?: string;
  tradition_b?: string;
}

// ── cleanup review (staged_cleanups, todo:b44966d0) ──────────────────

export interface PendingCleanup {
  target_id: number;
  chunk_id: string;
  tradition_id: string;
  section_label: string;
  text_id: string | null;
  original_body: string;
  proposed_body: string;
  justification: string;
  signal_score: number;
  words_preserved: boolean;
  model: string;
}

export interface CleanupsResponse {
  cleanups: PendingCleanup[];
  next_cursor: number | null;
  pending_cleanups_in_filter: number;
}

export interface CleanupFilterParams {
  tradition?: string;
  text?: string;
  min_signal?: number;
}

// ── unified queue (polymorphic) ──────────────────────────────────────

export interface QueueRowBase {
  action_id: number;
  client_action_id: string;
  target_table: 'staged_tags' | 'staged_edges' | 'staged_cleanups';
  action: ActionKind;
  reassign_to: string | null;
  reclassify_to: string | null;
  reviewer: string;
  created_at: string;
  target_id: number;
}

export interface QueueRowTag extends QueueRowBase {
  target_table: 'staged_tags';
  context: {
    kind: 'tag';
    chunk_id: string;
    concept_id: string;
    score: number;
    is_new_concept: boolean;
    section_label: string;
    tradition_id: string;
  };
}

export interface QueueRowEdge extends QueueRowBase {
  target_table: 'staged_edges';
  context: {
    kind: 'edge';
    source_chunk: string;
    target_chunk: string;
    edge_type: EdgeType;
    confidence: number;
    a: { section_label: string; tradition_id: string };
    b: { section_label: string; tradition_id: string };
  };
}

export interface QueueRowCleanup extends QueueRowBase {
  target_table: 'staged_cleanups';
  context: {
    kind: 'cleanup';
    chunk_id: string;
    signal_score: number;
    words_preserved: boolean;
    section_label: string;
    tradition_id: string;
  };
}

export type QueueRow = QueueRowTag | QueueRowEdge | QueueRowCleanup;

// ── shared ───────────────────────────────────────────────────────────

export interface Stats {
  pending_tags: number;
  pending_edges: number;
  pending_cleanups: number;
  queued_actions: number;
  queued_by_action: Record<string, number>;
  applied_today: number;
  applied_today_by_reviewer: Record<string, number>;
}

export interface ApplyResult {
  applied: number;
  edges_created: number;
  skipped_already_resolved: number;
  errors: Array<{ action_id: number; client_action_id: string; error: string }>;
  status: 'applied' | 'already_applied';
}

export interface ApplyPreview {
  total_queued: number;
  by_action: Record<string, number>;
  by_target_table: Record<string, number>;
  affected_staged_tags: number;
  affected_staged_edges: number;
  affected_staged_cleanups: number;
}

export type ActionKind = 'accept' | 'reject' | 'skip' | 'reassign' | 'reclassify';

export interface ActionPayload {
  action: ActionKind;
  reassign_to?: string;
  reclassify_to?: EdgeType | 'apparatus_drop';
  client_action_id: string;
  reviewer: string;
}

export interface FilterParams {
  tradition?: string;
  text?: string;
  concept?: string;
  min_score?: number;
}
