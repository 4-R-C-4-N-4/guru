import { useCallback, useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { api, newClientActionId } from '../api/client';
import type { ActionKind, CleanupFilterParams, PendingCleanup } from '../api/types';
import { CleanupCard, type CleanupAction } from '../components/CleanupCard';
import { getReviewerId, suggestDeviceName } from '../state/reviewer';
import { getCleanupCursor, saveCleanupCursor } from '../state/cleanupCursor';
import { enqueue as enqueueRetry } from '../state/queue';

// Cleanup deck (todo:b44966d0) — one staged_cleanups row at a time, exactly
// the EdgeDeck state machine with a numeric cursor and one queued action
// per item.

interface DeckState {
  current: PendingCleanup | null;
  queue: PendingCleanup[];
  cursor: number | null;
  loading: boolean;
  error: string | null;
  remainingInFilter: number;
}

function readFilters(params: URLSearchParams): CleanupFilterParams {
  return {
    tradition: params.get('tradition') ?? undefined,
    text: params.get('text') ?? undefined,
    min_signal: params.get('min_signal') ? Number(params.get('min_signal')) : undefined,
  };
}

export function CleanupDeck(): React.ReactElement {
  const [params] = useSearchParams();
  const filters = readFilters(params);

  const [reviewer, setReviewer] = useState<string | null>(null);
  const [state, setState] = useState<DeckState>({
    current: null,
    queue: [],
    cursor: null,
    loading: true,
    error: null,
    remainingInFilter: 0,
  });
  const [queuedById, setQueuedById] = useState<Map<number, CleanupAction>>(new Map());

  useEffect(() => {
    void (async () => {
      const r = await getReviewerId();
      setReviewer(r ?? suggestDeviceName());
    })();
  }, []);

  const fetchPage = useCallback(
    async (cursor: number | null): Promise<void> => {
      setState((s) => ({ ...s, loading: true, error: null }));
      try {
        const res = await api.cleanups({
          ...filters,
          cursor: cursor ?? undefined,
          limit: 8,
        });
        setState((s) => {
          const all = [...s.queue, ...res.cleanups];
          const [next, ...rest] = all;
          return {
            current: s.current ?? next ?? null,
            queue: s.current ? all : rest,
            cursor: res.next_cursor,
            loading: false,
            error: null,
            remainingInFilter: res.pending_cleanups_in_filter,
          };
        });
      } catch (e) {
        setState((s) => ({ ...s, loading: false, error: (e as Error).message }));
      }
    },
    [filters.tradition, filters.text, filters.min_signal],
  );

  const [resumed, setResumed] = useState(false);
  useEffect(() => {
    setState({ current: null, queue: [], cursor: null, loading: true, error: null, remainingInFilter: 0 });
    setResumed(false);
    void (async () => {
      const saved = await getCleanupCursor(filters);
      if (saved !== null) setResumed(true);
      void fetchPage(saved);
    })();
  }, [filters.tradition, filters.text, filters.min_signal, fetchPage]);

  useEffect(() => {
    if (state.cursor !== null) void saveCleanupCursor(filters, state.cursor);
  }, [state.cursor, filters.tradition, filters.text, filters.min_signal]);

  const advance = useCallback((): void => {
    setState((s) => {
      if (s.queue.length === 0) return { ...s, current: null };
      const [next, ...rest] = s.queue;
      return { ...s, current: next, queue: rest };
    });
  }, []);

  useEffect(() => {
    if (!state.current && state.cursor !== null && !state.loading) {
      void fetchPage(state.cursor);
    }
  }, [state.current, state.cursor, state.loading, fetchPage]);

  const queueAction = useCallback(
    async (cleanupId: number, kind: ActionKind, reclassify_to?: 'apparatus_drop'): Promise<void> => {
      if (!reviewer) return;
      const cid = newClientActionId();
      setQueuedById((prev) => {
        const m = new Map(prev);
        m.set(cleanupId, { kind, reclassify_to, client_action_id: cid });
        return m;
      });
      const payload = {
        action: kind,
        ...(reclassify_to ? { reclassify_to } : {}),
        client_action_id: cid,
        reviewer,
      };
      try {
        await api.postCleanupAction(cleanupId, payload);
      } catch {
        await enqueueRetry(cleanupId, payload, 'staged_cleanups');
      }
    },
    [reviewer],
  );

  const undoAction = useCallback(async (cleanupId: number): Promise<void> => {
    const queued = queuedById.get(cleanupId);
    if (!queued) return;
    if (queued.kind === 'skip') {
      setQueuedById((prev) => {
        const m = new Map(prev);
        m.delete(cleanupId);
        return m;
      });
      return;
    }
    try {
      await api.deleteQueued(queued.client_action_id);
      setQueuedById((prev) => {
        const m = new Map(prev);
        m.delete(cleanupId);
        return m;
      });
    } catch (e) {
      setState((s) => ({ ...s, error: `undo failed: ${(e as Error).message}` }));
    }
  }, [queuedById]);

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
    return (
      <div className="mx-auto max-w-md space-y-4 p-8 mono text-sm text-zinc-400">
        <p>No more cleanups in this filter.</p>
        <Link className="text-accent" to="/queue">View queue →</Link>
      </div>
    );
  }

  const queued = queuedById.get(state.current.target_id);

  return (
    <div className="mx-auto max-w-3xl space-y-4 px-3 py-4 sm:px-4">
      <div className="flex items-center justify-between mono text-xs text-zinc-500">
        <span>{state.remainingInFilter.toLocaleString()} pending cleanups in filter</span>
        <div className="flex gap-3">
          <Link to="/" className="text-zinc-400 hover:text-zinc-200">tags</Link>
          <Link to="/edges" className="text-zinc-400 hover:text-zinc-200">edges</Link>
          <Link to="/settings" className="text-zinc-400 hover:text-zinc-200">⚙</Link>
        </div>
      </div>

      {resumed && (
        <div className="rounded border border-zinc-700 bg-zinc-900 p-2 mono text-xs text-zinc-400">
          Resuming from your last position.
          <button
            className="ml-2 text-accent hover:underline"
            onClick={async () => {
              await saveCleanupCursor(filters, null);
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

      <CleanupCard
        cleanup={state.current}
        queued={queued}
        onAction={(kind, rt) => void queueAction(state.current!.target_id, kind, rt)}
        onUndo={() => void undoAction(state.current!.target_id)}
        onAdvance={advance}
      />
    </div>
  );
}
