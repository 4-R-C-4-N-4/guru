import type {
  ActionPayload,
  ApplyPreview,
  ApplyResult,
  Chunk,
  ChunksResponse,
  ConceptDef,
  EdgeFilterParams,
  EdgesResponse,
  FilterParams,
  PendingEdge,
  QueueRow,
  Stats,
} from './types';

const API_BASE = ''; // dev: vite proxy; prod: same-origin

export function newClientActionId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) return crypto.randomUUID();
  // RFC4122-compatible fallback
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { signal });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${path} → ${res.status}: ${text}`);
  }
  return (await res.json()) as T;
}

async function delJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'DELETE' });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return (await res.json()) as T;
}

export const api = {
  health: (): Promise<{ ok: true }> => getJson('/api/health'),
  stats: (): Promise<Stats> => getJson('/api/stats'),
  traditions: (): Promise<{ id: string }[]> => getJson('/api/traditions'),
  texts: (tradition: string): Promise<{ id: string }[]> =>
    getJson(`/api/texts?tradition=${encodeURIComponent(tradition)}`),
  concepts: (): Promise<ConceptDef[]> => getJson('/api/concepts'),

  chunks: (params: FilterParams & { cursor?: string; limit?: number }): Promise<ChunksResponse> => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
    }
    const qs = q.toString();
    return getJson(`/api/chunks${qs ? `?${qs}` : ''}`);
  },

  queue: (): Promise<{ actions: QueueRow[] }> => getJson('/api/queue'),

  postAction: (
    stagedTagId: number,
    payload: ActionPayload,
  ): Promise<{ ok: true; queued: boolean; idempotent?: boolean }> =>
    postJson(`/api/tags/${stagedTagId}/action`, payload),

  edges: (params: EdgeFilterParams & { cursor?: number; limit?: number }): Promise<EdgesResponse> => {
    const q = new URLSearchParams();
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== null && v !== '') q.set(k, String(v));
    }
    const qs = q.toString();
    return getJson(`/api/edges${qs ? `?${qs}` : ''}`);
  },

  edge: (id: number): Promise<{ edge: PendingEdge }> => getJson(`/api/edges/${id}`),

  postEdgeAction: (
    stagedEdgeId: number,
    payload: ActionPayload,
  ): Promise<{ ok: true; queued: boolean; idempotent?: boolean }> =>
    postJson(`/api/edges/${stagedEdgeId}/action`, payload),

  deleteQueued: (clientActionId: string): Promise<{ ok: true; deleted: number }> =>
    delJson(`/api/queue/${encodeURIComponent(clientActionId)}`),

  applyPreview: (): Promise<ApplyPreview> => getJson('/api/apply/preview'),

  apply: (clientActionId: string): Promise<ApplyResult> =>
    postJson('/api/apply', { client_action_id: clientActionId }),
};

export type { Chunk };
