import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';

const EDGE_TYPES: ('any' | 'PARALLELS' | 'CONTRASTS')[] = ['any', 'PARALLELS', 'CONTRASTS'];

export function EdgeFilter(): React.ReactElement {
  const [params] = useSearchParams();
  const nav = useNavigate();

  const [edgeType, setEdgeType] = useState<'any' | 'PARALLELS' | 'CONTRASTS'>(
    (params.get('edge_type') as 'PARALLELS' | 'CONTRASTS') ?? 'any',
  );
  const [minConfidence, setMinConfidence] = useState(
    Number(params.get('min_confidence') ?? 0),
  );
  const [traditionA, setTraditionA] = useState(params.get('tradition_a') ?? '');
  const [traditionB, setTraditionB] = useState(params.get('tradition_b') ?? '');

  const [traditions, setTraditions] = useState<string[]>([]);

  useEffect(() => {
    void api.traditions().then((rows) => setTraditions(rows.map((r) => r.id)));
  }, []);

  function apply(): void {
    const q = new URLSearchParams();
    if (edgeType !== 'any') q.set('edge_type', edgeType);
    if (minConfidence > 0) q.set('min_confidence', minConfidence.toFixed(2));
    if (traditionA) q.set('tradition_a', traditionA);
    if (traditionB) q.set('tradition_b', traditionB);
    nav(`/edges?${q.toString()}`);
  }

  function clear(): void {
    setEdgeType('any');
    setMinConfidence(0);
    setTraditionA('');
    setTraditionB('');
  }

  return (
    <div className="mx-auto max-w-md space-y-5 p-4 mono text-sm">
      <h2 className="text-zinc-300">Filter edges</h2>

      <Section label="Edge type">
        <div className="flex flex-wrap gap-2">
          {EDGE_TYPES.map((t) => (
            <Chip
              key={t}
              label={t}
              active={edgeType === t}
              onClick={() => setEdgeType(t)}
            />
          ))}
        </div>
      </Section>

      <Section label={`Min confidence: ${minConfidence.toFixed(2)}`}>
        <input
          type="range"
          min={0}
          max={1}
          step={0.05}
          value={minConfidence}
          onChange={(e) => setMinConfidence(Number(e.target.value))}
          className="w-full"
        />
        <div className="flex justify-between mono text-xs text-zinc-500">
          <span>0.00</span>
          <span>0.50</span>
          <span>1.00</span>
        </div>
      </Section>

      <Section label="Tradition A">
        <ChipRow options={traditions} value={traditionA} onChange={setTraditionA} />
      </Section>

      <Section label="Tradition B">
        <ChipRow options={traditions} value={traditionB} onChange={setTraditionB} />
      </Section>

      <p className="text-xs text-zinc-500">
        Tradition filters are symmetric — an edge matches when its two chunks' traditions
        are A and B in either order.
      </p>

      <div className="flex gap-3 pt-2">
        <button
          onClick={clear}
          className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-4 py-2 text-zinc-300 hover:bg-zinc-800"
        >
          Clear
        </button>
        <button
          onClick={apply}
          className="flex-1 rounded bg-accent px-4 py-2 text-black hover:opacity-90"
        >
          Apply filter
        </button>
      </div>
    </div>
  );
}

function Section({ label, children }: { label: string; children: React.ReactNode }): React.ReactElement {
  return (
    <div>
      <div className="mb-2 text-zinc-400">{label}</div>
      {children}
    </div>
  );
}

function ChipRow({
  options,
  value,
  onChange,
}: {
  options: string[];
  value: string;
  onChange: (v: string) => void;
}): React.ReactElement {
  return (
    <div className="flex flex-wrap gap-2">
      <Chip label="any" active={value === ''} onClick={() => onChange('')} />
      {options.map((o) => (
        <Chip key={o} label={o} active={value === o} onClick={() => onChange(o)} />
      ))}
    </div>
  );
}

function Chip({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}): React.ReactElement {
  return (
    <button
      onClick={onClick}
      className={`rounded-full border px-3 py-1 mono text-xs ${
        active
          ? 'border-accent bg-accent text-black'
          : 'border-zinc-700 bg-zinc-900 text-zinc-300 hover:bg-zinc-800'
      }`}
    >
      {label}
    </button>
  );
}
