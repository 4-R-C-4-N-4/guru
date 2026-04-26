import { useState } from 'react';
import type { Chunk, ActionKind } from '../api/types';
import { TagRow, type TagAction } from './TagRow';
import { ChunkActions } from './ChunkActions';

interface Props {
  chunk: Chunk;
  /** map target_id → queued action (undefined = still pending) */
  queued: Map<number, TagAction>;
  onTagAction: (stagedTagId: number, kind: ActionKind, reassign_to?: string) => void;
  onTagUndo: (stagedTagId: number) => void;
  onChunkBatch: (kind: Exclude<ActionKind, 'reassign'>) => void;
  onAdvance: () => void;
}

const BODY_PREVIEW_LEN = 1500;

export function ChunkCard({
  chunk,
  queued,
  onTagAction,
  onTagUndo,
  onChunkBatch,
  onAdvance,
}: Props): React.ReactElement {
  const [showFullBody, setShowFullBody] = useState(chunk.body.length <= BODY_PREVIEW_LEN);
  const remaining = chunk.pending_tags.filter((t) => !queued.has(t.target_id)).length;
  const allDone = remaining === 0;

  return (
    <article className="space-y-3 rounded-lg border border-zinc-800 bg-zinc-950 p-4">
      <div className="mono text-sm">
        <div className="flex items-baseline gap-1">
          <span className="label-col text-zinc-500">CHUNK:</span>
          <span className="break-all text-zinc-200">{chunk.chunk_id}</span>
        </div>
        <div className="flex items-baseline gap-1">
          <span className="label-col text-zinc-500">SECTION:</span>
          <span className="text-zinc-300">{chunk.section_label}</span>
        </div>
      </div>
      <hr className="border-zinc-800" />
      <div className="mono text-sm">
        <div className="text-zinc-500">BODY:</div>
        <div className="mt-1 whitespace-pre-wrap pl-4 text-zinc-200">
          {showFullBody ? chunk.body : `${chunk.body.slice(0, BODY_PREVIEW_LEN)}…`}
        </div>
        {chunk.body.length > BODY_PREVIEW_LEN && (
          <button
            onClick={() => setShowFullBody((s) => !s)}
            className="mt-1 pl-4 text-xs text-accent hover:underline"
          >
            {showFullBody ? '▴ collapse' : '▾ show more'}
          </button>
        )}
      </div>

      <hr className="border-zinc-800" />

      <div className="space-y-3">
        {chunk.pending_tags.map((tag, i) => (
          <TagRow
            key={tag.target_id}
            tag={tag}
            index={i}
            total={chunk.pending_tags.length}
            queued={queued.get(tag.target_id)}
            onAction={(kind, ra) => onTagAction(tag.target_id, kind, ra)}
            onUndo={() => onTagUndo(tag.target_id)}
          />
        ))}
      </div>

      <ChunkActions remaining={remaining} onBatch={onChunkBatch} />

      {allDone && (
        <button
          onClick={onAdvance}
          className="w-full rounded border border-accent bg-accent/10 px-4 py-3 mono text-sm text-accent hover:bg-accent/20"
        >
          Next Chunk →
        </button>
      )}
    </article>
  );
}
