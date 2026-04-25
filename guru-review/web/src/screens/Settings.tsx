import { useEffect, useState } from 'react';
import { getReviewerId, setReviewerId, suggestDeviceName } from '../state/reviewer';

export function Settings(): React.ReactElement {
  const [name, setName] = useState('');
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    void (async () => {
      const v = await getReviewerId();
      setName(v ?? suggestDeviceName());
    })();
  }, []);

  return (
    <div className="mx-auto max-w-md p-4 mono text-sm">
      <h2 className="mb-4 text-zinc-300">Reviewer device ID</h2>
      <p className="mb-3 text-zinc-500">
        Identifies which device made each review decision. Used in
        <code className="mx-1 text-accent">staged_tags.reviewed_by</code> when actions are applied.
      </p>
      <input
        className="w-full rounded border border-zinc-700 bg-zinc-900 px-3 py-2 text-zinc-100 mono"
        value={name}
        onChange={(e) => {
          setName(e.target.value);
          setSaved(false);
        }}
        placeholder="ivy-iphone"
      />
      <button
        className="mt-3 rounded bg-accent px-4 py-2 text-black hover:opacity-90"
        onClick={async () => {
          if (name.trim()) {
            await setReviewerId(name.trim());
            setSaved(true);
          }
        }}
      >
        Save
      </button>
      {saved && <span className="ml-3 text-emerald-400">saved</span>}
    </div>
  );
}
