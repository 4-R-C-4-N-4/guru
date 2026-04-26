import type { ActionKind } from '../api/types';

interface Props {
  onAction: (kind: Exclude<ActionKind, 'reassign' | 'reclassify'>) => void;
  onReclassify: () => void;
}

export function EdgeActions({ onAction, onReclassify }: Props): React.ReactElement {
  return (
    <div className="border-t border-zinc-800 pt-3 mono text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <button
          onClick={() => onAction('reject')}
          className="flex-1 rounded border border-rose-500/40 bg-rose-500/10 px-3 py-2 text-rose-300 hover:bg-rose-500/20"
        >
          Reject
        </button>
        <button
          onClick={() => onAction('skip')}
          className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-300 hover:bg-zinc-800"
        >
          Skip
        </button>
        <button
          onClick={() => onAction('accept')}
          className="flex-1 rounded border border-emerald-500/40 bg-emerald-500/10 px-3 py-2 text-emerald-300 hover:bg-emerald-500/20"
        >
          Accept
        </button>
        <button
          onClick={onReclassify}
          className="basis-full rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-amber-300 hover:bg-amber-500/20"
        >
          Reclassify…
        </button>
      </div>
    </div>
  );
}
