import type { ActionKind } from '../api/types';

interface Props {
  remaining: number;
  onBatch: (kind: Exclude<ActionKind, 'reassign'>) => void;
}

export function ChunkActions({ remaining, onBatch }: Props): React.ReactElement {
  const disabled = remaining === 0;
  const baseBtn =
    'flex-1 rounded border px-3 py-2 mono text-sm transition-colors disabled:opacity-30 disabled:cursor-not-allowed';
  return (
    <div className="rounded border border-zinc-700 bg-zinc-950 p-3">
      <div className="mb-2 mono text-xs text-zinc-500">
        Chunk-level ({remaining} remaining):
      </div>
      <div className="flex gap-2">
        <button
          disabled={disabled}
          onClick={() => onBatch('reject')}
          className={`${baseBtn} border-rose-500/40 bg-rose-500/10 text-rose-300 hover:bg-rose-500/20`}
        >
          Reject Remaining ({remaining})
        </button>
        <button
          disabled={disabled}
          onClick={() => onBatch('skip')}
          className={`${baseBtn} border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800`}
        >
          Defer ({remaining})
        </button>
        <button
          disabled={disabled}
          onClick={() => onBatch('accept')}
          className={`${baseBtn} border-emerald-500/40 bg-emerald-500/10 text-emerald-300 hover:bg-emerald-500/20`}
        >
          Accept Remaining ({remaining})
        </button>
      </div>
    </div>
  );
}
