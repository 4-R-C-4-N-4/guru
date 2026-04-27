import type { EdgeType } from '../api/types';

interface Props {
  open: boolean;
  currentType: EdgeType;
  onPick: (t: EdgeType) => void;
  onCancel: () => void;
}

interface TypeOption {
  type: EdgeType;
  label: string;
  blurb: string;
  // pill class kept in sync with EdgeCard's TYPE_PILL.
  pill: string;
  rejects: boolean;
}

const OPTIONS: TypeOption[] = [
  {
    type: 'PARALLELS',
    label: 'PARALLELS',
    blurb: 'Both passages assert the same idea (a real parallel relation).',
    pill: 'border-sky-500/40 bg-sky-500/15 text-sky-300',
    rejects: false,
  },
  {
    type: 'CONTRASTS',
    label: 'CONTRASTS',
    blurb: 'Both passages address the same idea but disagree (a contrast relation).',
    pill: 'border-amber-500/40 bg-amber-500/15 text-amber-300',
    rejects: false,
  },
  {
    type: 'surface_only',
    label: 'surface_only',
    blurb: 'Lexical/formal echo without substantive overlap. Marks the edge rejected.',
    pill: 'border-zinc-700 bg-zinc-800 text-zinc-300',
    rejects: true,
  },
  {
    type: 'unrelated',
    label: 'unrelated',
    blurb: "The two passages don't actually relate. Marks the edge rejected.",
    pill: 'border-zinc-700 bg-zinc-800 text-zinc-400',
    rejects: true,
  },
];

export function EdgeReclassifySheet({ open, currentType, onPick, onCancel }: Props): React.ReactElement | null {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-40 bg-black/70" onClick={onCancel}>
      <div
        className="absolute inset-x-0 bottom-0 max-h-[85vh] overflow-y-auto rounded-t-xl border-t border-zinc-800 bg-zinc-950 p-4 mono text-sm shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="reclassify edge"
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-zinc-200">Reclassify edge</h3>
          <button onClick={onCancel} className="text-zinc-500 hover:text-zinc-300">
            cancel
          </button>
        </div>
        <p className="mb-3 text-xs text-zinc-500">
          Choose the relation that best fits. Picking <code>surface_only</code> or{' '}
          <code>unrelated</code> marks the edge rejected — there's no such relation in the live
          graph, so the auto-promoted edge will be deleted.
        </p>
        <div className="space-y-2">
          {OPTIONS.filter((o) => o.type !== currentType).map((o) => (
            <button
              key={o.type}
              onClick={() => onPick(o.type)}
              className="w-full rounded border border-zinc-800 bg-zinc-900 px-3 py-3 text-left hover:border-zinc-600 hover:bg-zinc-800"
            >
              <div className="flex items-center gap-2">
                <span className={`rounded-full border px-2 py-0.5 mono text-xs ${o.pill}`}>
                  {o.label}
                </span>
                {o.rejects && (
                  <span className="rounded border border-rose-500/40 bg-rose-500/10 px-1.5 py-0.5 mono text-[10px] text-rose-300">
                    rejects
                  </span>
                )}
              </div>
              <div className="mt-1 text-xs text-zinc-400">{o.blurb}</div>
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
