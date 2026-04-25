import { useEffect, useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { api } from '../api/client';

export function Filter(): React.ReactElement {
  const [params] = useSearchParams();
  const nav = useNavigate();

  const [tradition, setTradition] = useState(params.get('tradition') ?? '');
  const [text, setText] = useState(params.get('text') ?? '');
  const [concept, setConcept] = useState(params.get('concept') ?? '');
  const [minScore, setMinScore] = useState(Number(params.get('min_score') ?? 1));

  const [traditions, setTraditions] = useState<string[]>([]);
  const [texts, setTexts] = useState<string[]>([]);

  useEffect(() => {
    void api.traditions().then((rows) => setTraditions(rows.map((r) => r.id)));
  }, []);

  useEffect(() => {
    if (!tradition) {
      setTexts([]);
      return;
    }
    void api.texts(tradition).then((rows) => setTexts(rows.map((r) => r.id)));
  }, [tradition]);

  function apply(): void {
    const q = new URLSearchParams();
    if (tradition) q.set('tradition', tradition);
    if (text) q.set('text', text);
    if (concept) q.set('concept', concept);
    if (minScore !== 1) q.set('min_score', String(minScore));
    nav(`/?${q.toString()}`);
  }

  function clear(): void {
    setTradition('');
    setText('');
    setConcept('');
    setMinScore(1);
  }

  return (
    <div className="mx-auto max-w-md space-y-5 p-4 mono text-sm">
      <h2 className="text-zinc-300">Filter</h2>

      <Section label="Tradition">
        <ChipRow
          options={traditions}
          value={tradition}
          onChange={(v) => {
            setTradition(v);
            setText(''); // texts depend on tradition
          }}
        />
      </Section>

      <Section label="Text">
        {tradition ? (
          texts.length > 0 ? (
            <ChipRow options={texts} value={text} onChange={setText} />
          ) : (
            <span className="text-zinc-600">no texts in {tradition}</span>
          )
        ) : (
          <span className="text-zinc-600">pick a tradition first</span>
        )}
      </Section>

      <Section label="Concept (exact concept_id match)">
        <input
          value={concept}
          onChange={(e) => setConcept(e.target.value)}
          placeholder="e.g. apophatic_theology"
          className="w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 mono"
        />
        <p className="mt-1 text-xs text-zinc-500">
          Filtering by concept shows chunks containing that concept among their pending tags
          (and all the chunk's other pending tags too) — chunk-grouped semantics, not per-tag.
        </p>
      </Section>

      <Section label={`Min score: ${minScore}`}>
        <input
          type="range"
          min={0}
          max={3}
          step={1}
          value={minScore}
          onChange={(e) => setMinScore(Number(e.target.value))}
          className="w-full"
        />
        <div className="flex justify-between mono text-xs text-zinc-500">
          <span>0</span>
          <span>1 (default)</span>
          <span>2</span>
          <span>3</span>
        </div>
      </Section>

      <div className="flex gap-3 pt-2">
        <button onClick={clear} className="flex-1 rounded border border-zinc-700 bg-zinc-900 px-4 py-2 text-zinc-300 hover:bg-zinc-800">
          Clear
        </button>
        <button onClick={apply} className="flex-1 rounded bg-accent px-4 py-2 text-black hover:opacity-90">
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

function Chip({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }): React.ReactElement {
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
