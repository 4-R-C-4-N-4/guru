import { useState } from 'react';
import type { PendingTag, ActionKind } from '../api/types';
import { ScoreBadge } from './ScoreBadge';
import { ConceptDef } from './ConceptDef';
import { ConceptPicker } from './ConceptPicker';

export interface TagAction {
  kind: ActionKind;
  reassign_to?: string;
  client_action_id: string;
}

interface Props {
  tag: PendingTag;
  index: number;
  total: number;
  /** undefined = pending, otherwise the queued action this tag has been bound to. */
  queued: TagAction | undefined;
  onAction: (kind: ActionKind, reassign_to?: string) => void;
  onUndo: () => void;
}

const VERB: Record<ActionKind, string> = {
  accept: '✓ accepted',
  reject: '✗ rejected',
  skip: '↪ skipped',
  reassign: '⤳ reassigned',
};

const VERB_COLOR: Record<ActionKind, string> = {
  accept: 'text-emerald-400',
  reject: 'text-rose-400',
  skip: 'text-zinc-500',
  reassign: 'text-amber-400',
};

export function TagRow({ tag, index, total, queued, onAction, onUndo }: Props): React.ReactElement {
  const [pickerOpen, setPickerOpen] = useState(false);
  const isQueued = queued !== undefined;

  return (
    <div
      className={`rounded border p-3 ${
        isQueued ? 'border-zinc-800 bg-zinc-900/40 opacity-70' : 'border-zinc-700 bg-zinc-900'
      }`}
    >
      <div className="mb-1 flex items-center justify-between mono text-xs text-zinc-500">
        <span>TAG {index + 1} of {total}</span>
        {isQueued && (
          <button onClick={onUndo} className={`mono ${VERB_COLOR[queued!.kind]} hover:underline`}>
            {VERB[queued!.kind]} · undo
          </button>
        )}
      </div>
      <div className="mono text-sm">
        <div className="flex items-baseline gap-1">
          <span className="label-col text-zinc-500">CONCEPT:</span>
          <span className={tag.is_new_concept ? 'italic text-amber-300' : 'text-zinc-100'}>
            {tag.concept_id}
            {tag.is_new_concept && <span className="ml-1 text-xs">(proposed)</span>}
          </span>
          <span className="ml-auto"><ScoreBadge score={tag.score} /></span>
        </div>
        <div className="flex items-baseline gap-1">
          <span className="label-col text-zinc-500">LLM:</span>
          <span className="flex-1 whitespace-pre-wrap text-zinc-300">{tag.justification || '(no justification)'}</span>
        </div>
        <div className="mt-1 pl-[9ch]">
          {tag.is_new_concept ? (
            <>
              <div className="mb-1 mono text-xs text-amber-400">PROPOSED CONCEPT — review carefully</div>
              <ConceptDef definition={tag.new_concept_def ?? ''} proposed />
            </>
          ) : (
            <ConceptDef definition={tag.concept_def} />
          )}
        </div>
      </div>

      {!isQueued && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-zinc-800 pt-3 mono text-sm">
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
            onClick={() => setPickerOpen(true)}
            className="basis-full rounded border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-amber-300 hover:bg-amber-500/20"
          >
            Reassign…
          </button>
        </div>
      )}

      <ConceptPicker
        open={pickerOpen}
        excludeConceptId={tag.concept_id}
        onPick={(cid) => {
          setPickerOpen(false);
          onAction('reassign', cid);
        }}
        onCancel={() => setPickerOpen(false)}
      />
    </div>
  );
}
