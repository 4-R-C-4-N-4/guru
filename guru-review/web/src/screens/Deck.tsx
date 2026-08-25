import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, newClientActionId } from '../api/client';
import type { ActionKind, Chunk } from '../api/types';
import { ChunkCard } from '../components/ChunkCard';
import type { TagAction } from '../components/TagRow';
import { getReviewerId, suggestDeviceName } from '../state/reviewer';
import { getCursor, saveCursor } from '../state/cursor';
import { enqueue as enqueueRetry } from '../state/queue';

interface DeckState {
  current: Chunk | null;
  queue: Chunk[]; // chunks fetched but not yet shown
  cursor: string | null;
  loading: boolean;
  error: string | null;
  remainingInFilter: number;
  tagsInFilter: number;
}

export function Deck(): React.ReactElement {
  const [params] = useSearchParams();
  const filters = {
    tradition: params.get('tradition') ?? undefined,
    text: params.get('text') ?? undefined,
    concept: params.get('concept') ?? undefined,
    min_score: params.get('min_score') ? Number(params.get('min_score')) : 1,
  };

  const [reviewer, setReviewer] = useState<string | null>(null);
  const [state, setState] = useState<DeckState>({
    current: null,
    queue: [],
    cursor: null,
    loading: true,
    error: null,
    remainingInFilter: 0,
    tagsInFilter: 0,
  });
  // Per-chunk local action tracking. Map keyed by chunk_id, value is map of target_id → TagAction.
  const [queuedByChunk, setQueuedByChunk] = useState<Record<string, Map<number, TagAction>>>({});

  useEffect(() => {
    void (async () => {
      const r = await getReviewerId();
      setReviewer(r ?? suggestDeviceName());
    })();
  }, []);

  // Spot-check deep link (todo:b72f6908): /?chunk=<chunk_id> fetches that
  // one chunk directly — with its reviewed verdicts via include_reviewed —
  // bypassing the filter/cursor flow. Used from the queue/apply screens.
  // The server's ?chunk= lookup has no pending constraint, so fully-reviewed
  // chunks are reachable; a miss surfaces as an explicit not-found state,
  // never as a silently blank deck.
  const focusChunk = params.get('chunk') ?? undefined;

  const fetchPage = useCallback(
    async (cursor: string | null): Promise<void> => {
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        if (focusChunk) {
          const res = await api.chunks({
            ...filters,
            chunk: focusChunk,
            cursor: undefined,
            limit: 1,
            include_reviewed: true,
          });
          const hit = res.chunks.find((c) => c.chunk_id === focusChunk);
          setState((s) =>
            hit
              ? { ...s, loading: false, error: null, current: hit, queue: [], cursor: null }
              : {
                  ...s,
                  loading: false,
                  error: `chunk ${focusChunk} not found`,
                },
          );
          return;
        }
        const res = await api.chunks({
          ...filters,
          cursor: cursor ?? undefined,
          limit: 6,
        });
        setState((s) => {
          const allChunks = [...s.queue, ...res.chunks];
          const [next, ...rest] = allChunks;
          return {
            current: s.current ?? next ?? null,
            queue: s.current ? allChunks : rest,
            cursor: res.next_cursor,
            loading: false,
            error: null,
            remainingInFilter: res.pending_chunks_in_filter,
            tagsInFilter: res.pending_tags_in_filter,
          };
        });
      } catch (e) {
        setState((s) => ({ ...s, loading: false, error: (e as Error).message }));
      }
    },
    [filters.tradition, filters.text, filters.concept, filters.min_score, focusChunk],
  );

  // Initial load + reload on filter change. Restore cursor from IndexedDB
  // if the user has reviewed this filter before. Skipped in focus mode:
  // the saved cursor is irrelevant to a single-chunk spot-check, and the
  // "Resuming" banner would be misleading (todo:b72f6908 review).
  const [resumed, setResumed] = useState(false);
  useEffect(() => {
    setState({
      current: null,
      queue: [],
      cursor: null,
      loading: true,
      error: null,
      remainingInFilter: 0,
      tagsInFilter: 0,
    });
    setResumed(false);
    void (async () => {
      const saved = focusChunk ? null : await getCursor(filters);
      if (saved) setResumed(true);
      void fetchPage(saved);
    })();
  }, [filters.tradition, filters.text, filters.concept, filters.min_score, fetchPage, focusChunk]);

  // Persist cursor on every successful page load (after the first one).
  useEffect(() => {
    if (state.cursor !== null) {
      void saveCursor(filters, state.cursor);
    }
  }, [state.cursor, filters.tradition, filters.text, filters.concept, filters.min_score]);

  const advance = useCallback((): void => {
    setState((s) => {
      if (s.queue.length === 0) {
        // Need to fetch next page
        return { ...s, current: null };
      }
      const [next, ...rest] = s.queue;
      return { ...s, current: next, queue: rest };
    });
  }, []);

  // After advancing, if current is null and there's a cursor, fetch.
  useEffect(() => {
    if (!state.current && state.cursor && !state.loading) {
      void fetchPage(state.cursor);
    }
  }, [state.current, state.cursor, state.loading, fetchPage]);

  const queueAction = useCallback(
    async (chunkId: string, stagedTagId: number, kind: ActionKind, reassign_to?: string): Promise<void> => {
      if (!reviewer) return;
      const cid = newClientActionId();
      // Optimistic local state
      setQueuedByChunk((prev) => {
        const m = new Map(prev[chunkId] ?? []);
        m.set(stagedTagId, { kind, reassign_to, client_action_id: cid });
        return { ...prev, [chunkId]: m };
      });
      const payload = {
        action: kind,
        ...(reassign_to ? { reassign_to } : {}),
        client_action_id: cid,
        reviewer,
      };
      try {
        await api.postAction(stagedTagId, payload);
      } catch {
        // Push to local retry queue; optimistic state stays. Drain loop
        // will retry with backoff when connectivity returns.
        await enqueueRetry(stagedTagId, payload);
      }
    },
    [reviewer],
  );

  const undoAction = useCallback(async (chunkId: string, stagedTagId: number): Promise<void> => {
    const queued = queuedByChunk[chunkId]?.get(stagedTagId);
    if (!queued) return;
    // Skips have no server-side row to delete
    if (queued.kind === 'skip') {
      setQueuedByChunk((prev) => {
        const m = new Map(prev[chunkId] ?? []);
        m.delete(stagedTagId);
        return { ...prev, [chunkId]: m };
      });
      return;
    }
    try {
      await api.deleteQueued(queued.client_action_id);
      setQueuedByChunk((prev) => {
        const m = new Map(prev[chunkId] ?? []);
        m.delete(stagedTagId);
        return { ...prev, [chunkId]: m };
      });
    } catch (e) {
      setState((s) => ({ ...s, error: `undo failed: ${(e as Error).message}` }));
    }
  }, [queuedByChunk]);

  const batchAction = useCallback(
    async (chunk: Chunk, kind: Exclude<ActionKind, 'reassign'>): Promise<void> => {
      const queued = queuedByChunk[chunk.chunk_id] ?? new Map();
      const remaining = chunk.pending_tags.filter((t) => !queued.has(t.target_id));
      // Fire sequentially for predictable error handling; small N (1-7 typical).
      for (const t of remaining) {
        await queueAction(chunk.chunk_id, t.target_id, kind);
      }
    },
    [queuedByChunk, queueAction],
  );

  if (state.loading && !state.current) {
    return <div className="mx-auto max-w-md p-8 mono text-sm text-zinc-500">loading…</div>;
  }
  if (state.error && !state.current) {
    return (
      <div className="mx-auto max-w-md p-8 mono text-sm text-rose-400">
        Error: {state.error}
        <button className="mt-3 block text-accent" onClick={() => void fetchPage(null)}>retry</button>
      </div>
    );
  }
  if (!state.current) {
    // Softlock guard (todo:1265031d): skipped chunks return to the pending
    // pool behind the saved resume cursor after an apply. Offer the reset
    // in the empty state (same fix as the edge/cleanup decks).
    return (
      <div className="mx-auto max-w-md space-y-4 p-8 mono text-sm text-zinc-400">
        {state.remainingInFilter > 0 ? (
          <>
            <p>
              {state.remainingInFilter.toLocaleString()} pending in this filter, but they
              sit behind your saved position (skipped items return to the pool after an apply).
            </p>
            <button
              className="rounded border border-accent bg-accent/10 px-4 py-2 text-accent hover:bg-accent/20"
              onClick={async () => {
                await saveCursor(filters, null);
                setState((s) => ({ ...s, current: null, queue: [], cursor: null }));
                void fetchPage(null);
              }}
            >
              Start from top →
            </button>
          </>
        ) : (
          <p>No more chunks in this filter.</p>
        )}
        <Link className="text-accent" to="/queue">View queue →</Link>
      </div>
    );
  }

  const currentChunkQueued = queuedByChunk[state.current.chunk_id] ?? new Map<number, TagAction>();

  return (
    <div className="mx-auto max-w-2xl space-y-4 px-3 py-4 sm:px-4">
      <div className="flex items-center justify-between mono text-xs text-zinc-500">
        <span>
          {state.remainingInFilter.toLocaleString()} chunks · {state.tagsInFilter.toLocaleString()} tags in filter
        </span>
        <div className="flex gap-3">
          <Link to="/filter" className="text-zinc-400 hover:text-zinc-200">filter</Link>
          <Link to="/settings" className="text-zinc-400 hover:text-zinc-200">⚙</Link>
        </div>
      </div>

      {resumed && (
        <div className="rounded border border-zinc-700 bg-zinc-900 p-2 mono text-xs text-zinc-400">
          Resuming from your last position.
          <button
            className="ml-2 text-accent hover:underline"
            onClick={async () => {
              await saveCursor(filters, null);
              setResumed(false);
              setState((s) => ({ ...s, current: null, queue: [], cursor: null }));
              void fetchPage(null);
            }}
          >
            Start from top
          </button>
        </div>
      )}

      {state.error && (
        <div className="rounded border border-rose-500/40 bg-rose-500/10 p-3 mono text-xs text-rose-300">
          {state.error}
        </div>
      )}

      <ChunkCard
        chunk={state.current}
        queued={currentChunkQueued}
        onTagAction={(sid, kind, ra) => void queueAction(state.current!.chunk_id, sid, kind, ra)}
        onTagUndo={(sid) => void undoAction(state.current!.chunk_id, sid)}
        onChunkBatch={(kind) => void batchAction(state.current!, kind)}
        onAdvance={advance}
      />
    </div>
  );
}
