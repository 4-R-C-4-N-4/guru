import { useState } from 'react';

interface Props {
  definition: string;
  proposed?: boolean;
}

export function ConceptDef({ definition, proposed }: Props): React.ReactElement {
  const [open, setOpen] = useState(false);
  const label = proposed ? 'proposed definition' : 'definition';
  if (!definition) {
    return <div className="mono text-xs text-zinc-600">no definition</div>;
  }
  return (
    <div className="mono text-xs">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="text-zinc-400 hover:text-zinc-200"
      >
        {open ? '▾' : '▸'} {label}
      </button>
      {open && (
        <div className="mt-1 whitespace-pre-wrap pl-4 text-zinc-300">{definition}</div>
      )}
    </div>
  );
}
