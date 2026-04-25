import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { api } from '../api/client';
import type { Stats } from '../api/types';

export function HeaderBar(): React.ReactElement {
  const [stats, setStats] = useState<Stats | null>(null);

  useEffect(() => {
    let cancelled = false;
    const tick = async (): Promise<void> => {
      try {
        const s = await api.stats();
        if (!cancelled) setStats(s);
      } catch {
        // swallow — header is best-effort
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
    <header className="sticky top-0 z-30 border-b border-zinc-800 bg-black/95 backdrop-blur supports-[backdrop-filter]:bg-black/70">
      <div className="flex items-center justify-between px-4 py-3 mono text-sm">
        <Link to="/" className="font-bold text-accent">guru-review</Link>
        {stats ? (
          <div className="flex items-center gap-3 text-zinc-400">
            <span>{stats.queued_actions} queued</span>
            <span>·</span>
            <span>{stats.pending_tags.toLocaleString()} pending</span>
            <Link to="/queue" className="rounded border border-accent/50 px-2 py-1 text-accent hover:bg-accent/10">
              Apply {stats.queued_actions > 0 ? stats.queued_actions : ''}
            </Link>
          </div>
        ) : (
          <span className="text-zinc-600">…</span>
        )}
      </div>
    </header>
  );
}
