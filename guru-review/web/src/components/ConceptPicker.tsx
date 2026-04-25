import { useEffect, useMemo, useState } from 'react';
import { api } from '../api/client';
import type { ConceptDef } from '../api/types';

interface Props {
  open: boolean;
  excludeConceptId?: string;
  onPick: (conceptId: string) => void;
  onCancel: () => void;
}

export function ConceptPicker({ open, excludeConceptId, onPick, onCancel }: Props): React.ReactElement | null {
  const [concepts, setConcepts] = useState<ConceptDef[]>([]);
  const [filter, setFilter] = useState('');
  const [free, setFree] = useState('');

  useEffect(() => {
    if (!open) return;
    setFilter('');
    setFree('');
    void api.concepts().then(setConcepts);
  }, [open]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return concepts
      .filter((c) => c.concept_id !== excludeConceptId)
      .filter((c) => !q || c.label.toLowerCase().includes(q) || c.concept_id.includes(q));
  }, [concepts, filter, excludeConceptId]);

  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-end justify-center bg-black/60" onClick={onCancel}>
      <div
        className="w-full max-w-md rounded-t-xl border-t border-zinc-700 bg-zinc-950 p-4 mono text-sm shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="reassign to concept"
      >
        <div className="mb-3 flex items-center justify-between">
          <h3 className="text-zinc-300">Reassign to…</h3>
          <button onClick={onCancel} className="text-zinc-500 hover:text-zinc-300">
            cancel
          </button>
        </div>
        <input
          autoFocus
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder="filter concepts"
          className="mb-3 w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 mono"
        />
        <ul className="max-h-72 overflow-y-auto rounded border border-zinc-800">
          {filtered.map((c) => (
            <li
              key={c.concept_id}
              className="cursor-pointer border-b border-zinc-900 px-3 py-2 hover:bg-zinc-900"
              onClick={() => onPick(c.concept_id)}
            >
              <div className="text-zinc-200">{c.label}</div>
              <div className="text-xs text-zinc-500">{c.concept_id}</div>
              {c.definition && (
                <div className="mt-1 line-clamp-2 text-xs text-zinc-500">{c.definition}</div>
              )}
            </li>
          ))}
          {filtered.length === 0 && (
            <li className="px-3 py-3 text-zinc-500">no matches</li>
          )}
        </ul>
        <div className="mt-3 border-t border-zinc-800 pt-3">
          <div className="mb-2 text-xs text-zinc-500">…or propose a new concept_id:</div>
          <div className="flex gap-2">
            <input
              value={free}
              onChange={(e) => setFree(e.target.value)}
              placeholder="snake_case_id"
              className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 mono"
            />
            <button
              disabled={!free.trim()}
              onClick={() => onPick(free.trim())}
              className="rounded bg-accent px-3 py-2 text-black hover:opacity-90 disabled:opacity-30"
            >
              use
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
