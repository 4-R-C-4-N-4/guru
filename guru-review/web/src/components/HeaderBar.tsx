import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { Stats } from '../api/types';
import { StatsDrawer } from './StatsDrawer';
import { subscribe as subscribeRetry } from '../state/queue';

export function HeaderBar(): React.ReactElement {
  const [stats, setStats] = useState<Stats | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [retryCount, setRetryCount] = useState(0);

  useEffect(() => subscribeRetry(setRetryCount), []);

  useEffect(() => {
    let cancelled = false;
    const tick = async (): Promise<void> => {
      try {
        const s = await api.stats();
        if (!cancelled) setStats(s);
      } catch {
        // best-effort
      }
    };
    void tick();
    const id = setInterval(() => void tick(), 10_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, []);

  return (
    <>
      <header className="sticky top-0 z-30 border-b border-zinc-800 bg-black/95 backdrop-blur supports-[backdrop-filter]:bg-black/70">
        <div className="flex items-center justify-between px-4 py-3 mono text-sm">
          <div className="flex items-baseline gap-2">
            <Link to="/" className="font-bold text-accent">guru-review</Link>
            {retryCount > 0 && (
              <span
                className="rounded border border-amber-500/40 bg-amber-500/10 px-1.5 text-xs text-amber-300"
                title={`${retryCount} action(s) waiting to sync`}
              >
                {retryCount} offline
              </span>
            )}
          </div>
          {stats ? (
            <div className="flex items-center gap-3 text-zinc-400">
              <button
                onClick={() => setDrawerOpen(true)}
                className="hover:text-zinc-200"
                aria-label="session stats"
              >
                {stats.queued_actions} queued · {stats.pending_tags.toLocaleString()} pending
              </button>
              <Link to="/queue" className="rounded border border-accent/50 px-2 py-1 text-accent hover:bg-accent/10">
                Apply{stats.queued_actions > 0 ? ` ${stats.queued_actions}` : ''}
              </Link>
            </div>
          ) : (
            <span className="text-zinc-600">…</span>
          )}
        </div>
      </header>
      {drawerOpen && <StatsDrawer stats={stats} onClose={() => setDrawerOpen(false)} />}
    </>
  );
}
