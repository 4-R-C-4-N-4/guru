// Per-device cursor persistence for the edge deck. Mirrors state/cursor.ts
// but keyed under `edgecursor:` so tag and edge decks resume independently.
import { get, set, del } from 'idb-keyval';
import type { EdgeFilterParams } from '../api/types';

function filterHash(f: EdgeFilterParams): string {
  const sorted = Object.keys(f)
    .filter((k) => {
      const v = f[k as keyof EdgeFilterParams];
      return v !== undefined && v !== '' && v !== null;
    })
    .sort()
    .reduce<Record<string, unknown>>((acc, k) => {
      acc[k] = f[k as keyof EdgeFilterParams];
      return acc;
    }, {});
  return JSON.stringify(sorted);
}

function key(f: EdgeFilterParams): string {
  return `edgecursor:${filterHash(f)}`;
}

export async function getEdgeCursor(f: EdgeFilterParams): Promise<number | null> {
  const v = await get<number>(key(f));
  return typeof v === 'number' ? v : null;
}

export async function saveEdgeCursor(f: EdgeFilterParams, cursor: number | null): Promise<void> {
  if (cursor === null) await del(key(f));
  else await set(key(f), cursor);
}
