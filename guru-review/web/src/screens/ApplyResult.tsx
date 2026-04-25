import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { ApplyResult as ApplyResultT } from '../api/types';

export function ApplyResult(): React.ReactElement {
  const [result, setResult] = useState<ApplyResultT | null>(null);

  useEffect(() => {
    const raw = sessionStorage.getItem('lastApplyResult');
    if (!raw) return;
    try {
      setResult(JSON.parse(raw) as ApplyResultT);
    } catch {
      // ignore
    }
  }, []);

  if (!result) {
    return (
      <div className="mx-auto max-w-md p-8 mono text-sm text-zinc-500">
        No recent apply result. <Link to="/queue" className="text-accent">Back to queue</Link>
      </div>
    );
  }

  const isAlready = result.status === 'already_applied';

  return (
    <div className="mx-auto max-w-md space-y-4 p-4 mono text-sm">
      <h2 className="text-zinc-300">{isAlready ? 'Queue already empty' : 'Apply complete'}</h2>

      <div className="rounded border border-zinc-800 bg-zinc-950 p-4 space-y-2">
        <Row label="actions applied"      value={result.applied} accent />
        <Row label="edges created/updated" value={result.edges_created} />
        <Row label="skipped (already resolved)" value={result.skipped_already_resolved} />
        <Row label="errors" value={result.errors.length} />
      </div>

      {result.errors.length > 0 && (
        <details className="rounded border border-rose-500/40 bg-rose-500/10 p-3">
          <summary className="cursor-pointer text-rose-300">{result.errors.length} error(s)</summary>
          <ul className="mt-2 space-y-1 text-xs text-rose-200">
            {result.errors.map((e) => (
              <li key={e.action_id}>
                action {e.action_id} ({e.client_action_id}): {e.error}
              </li>
            ))}
          </ul>
        </details>
      )}

      <Link
        to="/"
        onClick={() => sessionStorage.removeItem('lastApplyResult')}
        className="block rounded bg-accent px-4 py-3 text-center text-black hover:opacity-90"
      >
        Start a new review batch →
      </Link>
    </div>
  );
}

function Row({ label, value, accent }: { label: string; value: number; accent?: boolean }): React.ReactElement {
  return (
    <div className="flex justify-between">
      <span className="text-zinc-400">{label}</span>
      <span className={`tabular-nums ${accent ? 'text-emerald-300' : 'text-zinc-200'}`}>
        {value.toLocaleString()}
      </span>
    </div>
  );
}
