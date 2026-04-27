import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { FixedSizeList as VList } from 'react-window';
import { api, newClientActionId } from '../api/client';
import type { ApplyPreview, QueueRow } from '../api/types';

export function Queue(): React.ReactElement {
  const nav = useNavigate();
  const [rows, setRows] = useState<QueueRow[] | null>(null);
  const [preview, setPreview] = useState<ApplyPreview | null>(null);
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
        <p className="text-zinc-500">Review some chunks or edges first, then come back here to apply.</p>
        <button onClick={() => nav('/')} className="rounded bg-accent px-4 py-2 text-black hover:opacity-90">
          Back to deck
        </button>
      </div>
    );
  }

  // Group by target_table so the operator can see tag- and edge-actions
  // separately. The §6 design calls for a `by_target_table` summary too.
  const tagRows = rows.filter((r): r is Extract<QueueRow, { target_table: 'staged_tags' }> => r.target_table === 'staged_tags');
  const edgeRows = rows.filter((r): r is Extract<QueueRow, { target_table: 'staged_edges' }> => r.target_table === 'staged_edges');
  const acceptCount = preview.by_action.accept ?? 0;

  return (
    <div className="mx-auto max-w-2xl space-y-4 p-3 sm:p-4 mono text-sm">
      <div className="rounded border border-zinc-800 bg-zinc-900 p-3">
        <div className="text-zinc-200">
          {preview.total_queued} queued
          {preview.affected_staged_tags > 0 && ` · ${preview.affected_staged_tags} staged_tags`}
          {preview.affected_staged_edges > 0 && ` · ${preview.affected_staged_edges} staged_edges`}
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

      {/* Virtualized list when >50; grouped sections otherwise. */}
      {rows.length > 50 ? (
        <VList
          height={Math.min(window.innerHeight - 240, 600)}
          width="100%"
          itemCount={rows.length}
          itemSize={64}
        >
          {({ index, style }: { index: number; style: React.CSSProperties }) => (
            <div style={style}>
              <ActionRow row={rows[index]} onUndo={(c) => void undo(c)} />
            </div>
          )}
        </VList>
      ) : (
        <div className="space-y-3">
          {tagRows.length > 0 && (
            <details open className="rounded border border-zinc-800 bg-zinc-950">
              <summary className="cursor-pointer px-3 py-2 text-zinc-300 hover:bg-zinc-900">
                staged_tags <span className="text-zinc-500">({tagRows.length})</span>
              </summary>
              <div>
                {tagRows.map((r) => (
                  <ActionRow key={r.client_action_id} row={r} onUndo={(c) => void undo(c)} />
                ))}
              </div>
            </details>
          )}
          {edgeRows.length > 0 && (
            <details open className="rounded border border-zinc-800 bg-zinc-950">
              <summary className="cursor-pointer px-3 py-2 text-zinc-300 hover:bg-zinc-900">
                staged_edges <span className="text-zinc-500">({edgeRows.length})</span>
              </summary>
              <div>
                {edgeRows.map((r) => (
                  <ActionRow key={r.client_action_id} row={r} onUndo={(c) => void undo(c)} />
                ))}
              </div>
            </details>
          )}
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
              This will create up to {acceptCount} new edges in
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

const ACTION_COLOR: Record<string, string> = {
  accept: 'text-emerald-400',
  reject: 'text-rose-400',
  skip: 'text-zinc-500',
  reassign: 'text-amber-400',
  reclassify: 'text-amber-400',
};

function ActionRow({ row, onUndo }: { row: QueueRow; onUndo: (cid: string) => void }): React.ReactElement {
  const color = ACTION_COLOR[row.action] ?? 'text-zinc-300';
  const ctx = row.context;
  return (
    <div className="flex items-center justify-between border-b border-zinc-900 px-3 py-2 last:border-0 mono text-xs">
      <div className="min-w-0 flex-1">
        {ctx.kind === 'tag' ? (
          <>
            <div className="truncate text-zinc-300">{ctx.section_label}</div>
            <div className="truncate text-zinc-500">
              {ctx.concept_id}
              {row.action === 'reassign' && row.reassign_to && <span> → {row.reassign_to}</span>}
            </div>
          </>
        ) : (
          <>
            <div className="truncate text-zinc-300">
              {ctx.edge_type} · {ctx.a.tradition_id}↔{ctx.b.tradition_id}
            </div>
            <div className="truncate text-zinc-500">
              {ctx.a.section_label} ↔ {ctx.b.section_label}
              {row.action === 'reclassify' && row.reclassify_to && <span> → {row.reclassify_to}</span>}
            </div>
          </>
        )}
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
