import { useState } from 'react';
import type { ActionKind, PendingCleanup } from '../api/types';

// Cleanup review card (todo:b44966d0): the model proposed a whitespace-only
// rewrite of a hard-wrapped chunk body. The reviewer compares BEFORE and
// AFTER, checks the mechanically-computed words-preserved badge, and either
// accepts the rewrite, rejects it, skips, or flags the whole chunk as
// editorial apparatus (drop candidate → todo:50438e23).

export interface CleanupAction {
  kind: ActionKind;
  reclassify_to?: 'apparatus_drop';
  client_action_id: string;
}

interface Props {
  cleanup: PendingCleanup;
  queued: CleanupAction | undefined;
  onAction: (kind: ActionKind, reclassify_to?: 'apparatus_drop') => void;
  onUndo: () => void;
  onAdvance: () => void;
}

const BODY_PREVIEW_LEN = 900;

const VERB: Record<ActionKind, string> = {
  accept: '✓ accepted',
  reject: '✗ rejected',
  skip: '↪ skipped',
  reassign: '⤳ reassigned',
  reclassify: '⚑ apparatus',
};

const VERB_COLOR: Record<ActionKind, string> = {
  accept: 'text-emerald-400',
  reject: 'text-rose-400',
  skip: 'text-zinc-500',
  reassign: 'text-amber-400',
  reclassify: 'text-amber-400',
};

export function CleanupCard({ cleanup, queued, onAction, onUndo, onAdvance }: Props): React.ReactElement {
  const [confirmApparatus, setConfirmApparatus] = useState(false);
  const isQueued = queued !== undefined;

  return (
    <article className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950 p-4">
      {/* banner ──────────────────────────────────────────────────── */}
      <div className="space-y-2 mono text-sm">
        <div className="flex items-center justify-between">
          <span className="label-col text-zinc-500">CHUNK:</span>
          <div className="ml-1 flex flex-1 items-center gap-2">
            <span className="truncate text-xs text-zinc-300">{cleanup.chunk_id}</span>
            <span className="text-xs text-zinc-500">wrap {cleanup.signal_score.toFixed(2)}</span>
            {cleanup.words_preserved ? (
              <span className="rounded-full border border-emerald-500/40 bg-emerald-500/15 px-2 py-0.5 mono text-xs text-emerald-300">
                ✓ words preserved
              </span>
            ) : (
              <span className="rounded-full border border-rose-500/40 bg-rose-500/15 px-2 py-0.5 mono text-xs text-rose-300">
                ✗ MODEL DRIFTED
              </span>
            )}
            {isQueued && (
              <button
                onClick={onUndo}
                className={`ml-auto mono text-xs ${VERB_COLOR[queued!.kind]} hover:underline`}
              >
                {VERB[queued!.kind]} · undo
              </button>
            )}
          </div>
        </div>
        <div className="flex items-baseline gap-1">
          <span className="label-col text-zinc-500">DIFF:</span>
          <span className="flex-1 whitespace-pre-wrap text-xs text-zinc-400">
            {cleanup.justification || '(no justification)'}
            {cleanup.model && ` · ${cleanup.model}`}
          </span>
        </div>
      </div>

      <hr className="border-zinc-800" />

      {/* before / after — stacked on phone, side-by-side on tablet+ ── */}
      <div className="grid gap-3 md:grid-cols-2">
        <BodyBlock label="BEFORE" tone="text-zinc-400" body={cleanup.original_body} meta={cleanup} />
        <BodyBlock label="AFTER" tone="text-zinc-200" body={cleanup.proposed_body} meta={cleanup} />
      </div>

      {!isQueued && !confirmApparatus && (
        <div className="grid grid-cols-4 gap-2">
          <button
            onClick={() => onAction('reject')}
            className="rounded border border-rose-500/40 bg-rose-500/10 px-2 py-3 mono text-sm text-rose-300 hover:bg-rose-500/20"
          >
            Reject
          </button>
          <button
            onClick={() => onAction('skip')}
            className="rounded border border-zinc-700 bg-zinc-900 px-2 py-3 mono text-sm text-zinc-400 hover:bg-zinc-800"
          >
            Skip
          </button>
          <button
            onClick={() => onAction('accept')}
            disabled={!cleanup.words_preserved}
            title={cleanup.words_preserved ? undefined : 'apply_cleanups.py refuses drifted rewrites'}
            className="rounded border border-emerald-500/40 bg-emerald-500/10 px-2 py-3 mono text-sm text-emerald-300 hover:bg-emerald-500/20 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Accept
          </button>
          <button
            onClick={() => setConfirmApparatus(true)}
            className="rounded border border-amber-500/40 bg-amber-500/10 px-2 py-3 mono text-sm text-amber-300 hover:bg-amber-500/20"
          >
            Apparatus…
          </button>
        </div>
      )}

      {!isQueued && confirmApparatus && (
        <div className="space-y-2 rounded border border-amber-500/40 bg-amber-500/10 p-3">
          <p className="mono text-xs text-amber-200">
            Flag this whole chunk as editorial apparatus (footnote block, errata,
            front-matter)? It joins the drop-candidate list for the apparatus
            ticket — no rewrite is applied, nothing is deleted.
          </p>
          <div className="grid grid-cols-2 gap-2">
            <button
              onClick={() => setConfirmApparatus(false)}
              className="rounded border border-zinc-700 bg-zinc-900 px-2 py-2 mono text-sm text-zinc-400 hover:bg-zinc-800"
            >
              Cancel
            </button>
            <button
              onClick={() => {
                setConfirmApparatus(false);
                onAction('reclassify', 'apparatus_drop');
              }}
              className="rounded border border-amber-500/40 bg-amber-500/15 px-2 py-2 mono text-sm text-amber-300 hover:bg-amber-500/25"
            >
              ⚑ Flag as apparatus
            </button>
          </div>
        </div>
      )}

      {isQueued && (
        <button
          onClick={onAdvance}
          className="w-full rounded border border-accent bg-accent/10 px-4 py-3 mono text-sm text-accent hover:bg-accent/20"
        >
          Next Cleanup →
        </button>
      )}
    </article>
  );
}

function BodyBlock({
  label, tone, body, meta,
}: { label: string; tone: string; body: string; meta: PendingCleanup }): React.ReactElement {
  const [showFull, setShowFull] = useState(body.length <= BODY_PREVIEW_LEN);
  const truncated = body.length > BODY_PREVIEW_LEN;
  return (
    <div className="rounded border border-zinc-800 bg-zinc-900/40 p-3 mono text-sm">
      <div className="mb-2 flex items-baseline gap-1">
        <span className="rounded bg-zinc-800 px-1.5 mono text-xs text-zinc-300">{label}</span>
        <span className="ml-1 truncate text-xs text-zinc-400">
          {meta.tradition_id}
          {meta.text_id && ` · ${meta.text_id}`}
          {meta.section_label && ` · ${meta.section_label}`}
        </span>
      </div>
      <div className={`whitespace-pre-wrap ${tone}`}>
        {showFull ? body : `${body.slice(0, BODY_PREVIEW_LEN)}…`}
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
