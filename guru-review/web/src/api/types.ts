export interface PendingTag {
  staged_tag_id: number;
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

export interface QueueRow {
  action_id: number;
  client_action_id: string;
  action: 'accept' | 'reject' | 'skip' | 'reassign';
  reassign_to: string | null;
  reviewer: string;
  created_at: string;
  staged_tag_id: number;
  chunk_id: string;
  concept_id: string;
  score: number;
  is_new_concept: number;
  section_label: string;
  tradition_id: string;
}

export interface Stats {
  pending_tags: number;
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

export type ActionKind = 'accept' | 'reject' | 'skip' | 'reassign';

export interface ActionPayload {
  action: ActionKind;
  reassign_to?: string;
  client_action_id: string;
  reviewer: string;
}

export interface FilterParams {
  tradition?: string;
  text?: string;
  concept?: string;
  min_score?: number;
}
