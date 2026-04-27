import { useState } from 'react';
import type { ActionKind, EdgeChunk, EdgeType, PendingEdge } from '../api/types';
import { EdgeActions } from './EdgeActions';
import { EdgeReclassifySheet } from './EdgeReclassifySheet';

export interface EdgeAction {
  kind: ActionKind;
  reclassify_to?: EdgeType;
  client_action_id: string;
}

interface Props {
  edge: PendingEdge;
  /** undefined = pending, otherwise the queued action this edge has been bound to. */
  queued: EdgeAction | undefined;
  onAction: (kind: ActionKind, reclassify_to?: EdgeType) => void;
  onUndo: () => void;
  onAdvance: () => void;
}

const BODY_PREVIEW_LEN = 600;

const TYPE_PILL: Record<EdgeType, string> = {
  PARALLELS: 'border-sky-500/40 bg-sky-500/15 text-sky-300',
  CONTRASTS: 'border-amber-500/40 bg-amber-500/15 text-amber-300',
  surface_only: 'border-zinc-700 bg-zinc-800 text-zinc-300',
  unrelated: 'border-zinc-700 bg-zinc-800 text-zinc-400',
};

const VERB: Record<ActionKind, string> = {
  accept: '✓ accepted',
  reject: '✗ rejected',
  skip: '↪ skipped',
  reassign: '⤳ reassigned',
  reclassify: '⤳ reclassified',
};

const VERB_COLOR: Record<ActionKind, string> = {
  accept: 'text-emerald-400',
  reject: 'text-rose-400',
  skip: 'text-zinc-500',
  reassign: 'text-amber-400',
  reclassify: 'text-amber-400',
};

export function EdgeCard({ edge, queued, onAction, onUndo, onAdvance }: Props): React.ReactElement {
  const [reclassifyOpen, setReclassifyOpen] = useState(false);
  const isQueued = queued !== undefined;
  const reclassifyLabel =
    queued?.kind === 'reclassify' && queued.reclassify_to ? ` → ${queued.reclassify_to}` : '';

  return (
    <article className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950 p-4">
      {/* edge banner ─────────────────────────────────────────────── */}
      <div className="space-y-2 mono text-sm">
        <div className="flex items-center justify-between">
          <span className="label-col text-zinc-500">EDGE:</span>
          <div className="ml-1 flex flex-1 items-center gap-2">
            <span
              className={`rounded-full border px-2 py-0.5 mono text-xs ${TYPE_PILL[edge.edge_type]}`}
            >
              {edge.edge_type}
            </span>
            <span className="text-xs text-zinc-500">
              conf {edge.confidence.toFixed(2)} · tier {edge.tier}
            </span>
            {isQueued && (
              <button
                onClick={onUndo}
                className={`ml-auto mono text-xs ${VERB_COLOR[queued!.kind]} hover:underline`}
              >
                {VERB[queued!.kind]}{reclassifyLabel} · undo
              </button>
            )}
          </div>
        </div>
        <div className="flex items-baseline gap-1">
          <span className="label-col text-zinc-500">LLM:</span>
          <span className="flex-1 whitespace-pre-wrap text-zinc-300">
            {edge.justification || '(no justification)'}
          </span>
        </div>
      </div>

      <hr className="border-zinc-800" />

      {/* two passages — stacked on phone, side-by-side on tablet+ ─── */}
      <div className="grid gap-3 md:grid-cols-2">
        <PassageBlock label="A" chunk={edge.a} />
        <PassageBlock label="B" chunk={edge.b} />
      </div>

      {!isQueued && (
        <EdgeActions
          onAction={(k) => onAction(k)}
          onReclassify={() => setReclassifyOpen(true)}
        />
      )}

      {isQueued && (
        <button
          onClick={onAdvance}
          className="w-full rounded border border-accent bg-accent/10 px-4 py-3 mono text-sm text-accent hover:bg-accent/20"
        >
          Next Edge →
        </button>
      )}

      <EdgeReclassifySheet
        open={reclassifyOpen}
        currentType={edge.edge_type}
        onPick={(t) => {
          setReclassifyOpen(false);
          onAction('reclassify', t);
        }}
        onCancel={() => setReclassifyOpen(false)}
      />
    </article>
  );
}

function PassageBlock({ label, chunk }: { label: string; chunk: EdgeChunk }): React.ReactElement {
  const [showFull, setShowFull] = useState(chunk.body.length <= BODY_PREVIEW_LEN);
  const truncated = chunk.body.length > BODY_PREVIEW_LEN;
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3 mono text-sm">
      <div className="mb-2 flex items-baseline gap-1">
        <span className="rounded bg-zinc-800 px-1.5 mono text-xs text-zinc-300">{label}</span>
        <span className="ml-1 truncate text-xs text-zinc-400">
          {chunk.tradition_id}
          {chunk.text_id && ` · ${chunk.text_id}`}
          {chunk.section_label && ` · ${chunk.section_label}`}
        </span>
      </div>
      <div className="whitespace-pre-wrap text-zinc-200">
        {showFull ? chunk.body : `${chunk.body.slice(0, BODY_PREVIEW_LEN)}…`}
      </div>
      {truncated && (
        <button
          onClick={() => setShowFull((s) => !s)}
          className="mt-1 text-xs text-accent hover:underline"
        >
          {showFull ? '▴ collapse' : '▾ show full body'}
        </button>
      )}
    </div>
  );
}
