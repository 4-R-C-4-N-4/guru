import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FixedSizeList as VList } from 'react-window';
import { api, newClientActionId } from '../api/client';
import type { QueueRow } from '../api/types';

export function Queue(): React.ReactElement {
  const nav = useNavigate();
  const [rows, setRows] = useState<QueueRow[] | null>(null);
  const [preview, setPreview] = useState<{
    total_queued: number;
    by_action: Record<string, number>;
    affected_staged_tags: number;
  } | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [applying, setApplying] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async (): Promise<void> => {
    try {
      const [q, p] = await Promise.all([api.queue(), api.applyPreview()]);
      setRows(q.actions);
      setPreview(p);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const undo = useCallback(
    async (cid: string): Promise<void> => {
      try {
        await api.deleteQueued(cid);
        await reload();
      } catch (e) {
        setError(`undo failed: ${(e as Error).message}`);
      }
    },
    [reload],
  );

  const apply = useCallback(async (): Promise<void> => {
    setApplying(true);
    setError(null);
    try {
      const result = await api.apply(newClientActionId());
      // Stash result so the result screen can render it
      sessionStorage.setItem('lastApplyResult', JSON.stringify(result));
      nav('/applied');
    } catch (e) {
      setError(`apply failed: ${(e as Error).message}`);
      setApplying(false);
    }
  }, [nav]);

  if (!rows || !preview) {
    return <div className="mx-auto max-w-md p-8 mono text-sm text-zinc-500">loading queue…</div>;
  }

  if (rows.length === 0) {
    return (
      <div className="mx-auto max-w-md space-y-4 p-8 mono text-sm">
        <h2 className="text-zinc-300">Queue empty</h2>
        <p className="text-zinc-500">Review some chunks first, then come back here to apply.</p>
        <button onClick={() => nav('/')} className="rounded bg-accent px-4 py-2 text-black hover:opacity-90">
          Back to deck
        </button>
      </div>
    );
  }

  // Group by tradition for collapsible sections.
  const byTradition = new Map<string, QueueRow[]>();
  for (const r of rows) {
    const arr = byTradition.get(r.tradition_id) ?? [];
    arr.push(r);
    byTradition.set(r.tradition_id, arr);
  }

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-3 sm:p-4 mono text-sm">
      <div className="rounded border border-zinc-800 bg-zinc-900 p-3">
        <div className="text-zinc-200">
          {preview.total_queued} queued · {preview.affected_staged_tags} staged_tags affected
        </div>
        <div className="mt-1 text-xs text-zinc-500">
          {Object.entries(preview.by_action)
            .map(([a, n]) => `${a} ${n}`)
            .join(' · ')}
        </div>
      </div>

      {error && (
        <div className="rounded border border-rose-500/40 bg-rose-500/10 p-3 text-xs text-rose-300">
          {error}
        </div>
      )}

      {/* Virtualized list when >50; group sections otherwise. */}
      {rows.length > 50 ? (
        <VList
          height={Math.min(window.innerHeight - 240, 600)}
          width="100%"
          itemCount={rows.length}
          itemSize={60}
        >
          {({ index, style }: { index: number; style: React.CSSProperties }) => (
            <div style={style}>
              <ActionRow row={rows[index]} onUndo={(c) => void undo(c)} />
            </div>
          )}
        </VList>
      ) : (
        <div className="space-y-3">
          {[...byTradition.entries()].map(([trad, items]) => (
            <details key={trad} open className="rounded border border-zinc-800 bg-zinc-950">
              <summary className="cursor-pointer px-3 py-2 text-zinc-300 hover:bg-zinc-900">
                {trad} <span className="text-zinc-500">({items.length})</span>
              </summary>
              <div>
                {items.map((r) => (
                  <ActionRow key={r.client_action_id} row={r} onUndo={(c) => void undo(c)} />
                ))}
              </div>
            </details>
          ))}
        </div>
      )}

      <div className="sticky bottom-0 -mx-3 border-t border-zinc-800 bg-black/95 p-3 backdrop-blur sm:-mx-4 sm:p-4">
        {!confirming ? (
          <button
            onClick={() => setConfirming(true)}
            disabled={rows.length === 0 || applying}
            className="w-full rounded bg-accent px-4 py-3 text-black hover:opacity-90 disabled:opacity-30"
          >
            Promote {rows.length} to live graph →
          </button>
        ) : (
          <div className="space-y-3">
            <div className="text-zinc-300">
              This will create up to {preview.by_action.accept ?? 0} new EXPRESSES edges in
              <code className="mx-1 text-accent">data/guru.db</code>. Continue?
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => setConfirming(false)}
                disabled={applying}
                className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-4 py-2 text-zinc-300 hover:bg-zinc-800"
              >
                Cancel
              </button>
              <button
                onClick={() => void apply()}
                disabled={applying}
                className="flex-1 rounded bg-emerald-500 px-4 py-2 text-black hover:opacity-90 disabled:opacity-30"
              >
                {applying ? 'applying…' : 'Yes, apply'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ActionRow({ row, onUndo }: { row: QueueRow; onUndo: (cid: string) => void }): React.ReactElement {
  const color = {
    accept: 'text-emerald-400',
    reject: 'text-rose-400',
    skip: 'text-zinc-500',
    reassign: 'text-amber-400',
  }[row.action];
  return (
    <div className="flex items-center justify-between border-b border-zinc-900 px-3 py-2 last:border-0 mono text-xs">
      <div className="min-w-0 flex-1">
        <div className="truncate text-zinc-300">{row.section_label}</div>
        <div className="truncate text-zinc-500">
          {row.concept_id}
          {row.action === 'reassign' && row.reassign_to && <span> → {row.reassign_to}</span>}
        </div>
      </div>
      <span className={`mx-3 ${color}`}>{row.action}</span>
      <button
        onClick={() => onUndo(row.client_action_id)}
        className="text-zinc-500 hover:text-zinc-200"
      >
        undo
      </button>
    </div>
  );
}
