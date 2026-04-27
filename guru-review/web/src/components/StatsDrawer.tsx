import type { Stats } from '../api/types';

interface Props {
  stats: Stats | null;
  onClose: () => void;
}

export function StatsDrawer({ stats, onClose }: Props): React.ReactElement {
  return (
    <div className="fixed inset-0 z-40 bg-black/60" onClick={onClose}>
      <div
        className="absolute right-0 top-0 h-full w-full max-w-sm overflow-y-auto border-l border-zinc-800 bg-zinc-950 p-5 mono text-sm shadow-2xl"
        onClick={(e) => e.stopPropagation()}
        role="dialog"
        aria-label="session stats"
      >
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-zinc-300">Session stats</h3>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300">close</button>
        </div>

        {!stats ? (
          <div className="text-zinc-500">loading…</div>
        ) : (
          <div className="space-y-4">
            <Section title="Today">
              <Row k="applied" v={stats.applied_today} />
              {Object.entries(stats.applied_today_by_reviewer).map(([reviewer, n]) => (
                <Row key={reviewer} k={`  ${reviewer}`} v={n} />
              ))}
            </Section>

            <Section title="Queue (un-applied)">
              <Row k="queued" v={stats.queued_actions} />
              {Object.entries(stats.queued_by_action).map(([k, v]) => (
                <Row key={k} k={`  ${k}`} v={v} />
              ))}
            </Section>

            <Section title="Pool">
              <Row k="pending tags" v={stats.pending_tags} />
              <Row k="pending edges" v={stats.pending_edges} />
            </Section>
          </div>
        )}
      </div>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }): React.ReactElement {
  return (
    <div>
      <div className="mb-1 text-zinc-400">{title}</div>
      <div className="rounded border border-zinc-800 bg-zinc-900/50 p-3 space-y-1">{children}</div>
    </div>
  );
}

function Row({ k, v }: { k: string; v: number }): React.ReactElement {
  return (
    <div className="flex justify-between">
      <span className="text-zinc-400">{k}</span>
      <span className="text-zinc-200 tabular-nums">{v.toLocaleString()}</span>
    </div>
  );
}
