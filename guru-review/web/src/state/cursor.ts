// Per-device cursor persistence (design.md §5.7.1, impl.md P10c).
// Key: cursor:<filter_hash>. Reviewer scoping is implicit (each device has
// its own IndexedDB).
import { get, set, del } from 'idb-keyval';
import type { FilterParams } from '../api/types';

function filterHash(f: FilterParams): string {
  const sorted = Object.keys(f)
    .filter((k) => f[k as keyof FilterParams] !== undefined && f[k as keyof FilterParams] !== '')
    .sort()
    .reduce<Record<string, unknown>>((acc, k) => {
      acc[k] = f[k as keyof FilterParams];
      return acc;
    }, {});
  return JSON.stringify(sorted);
}

function key(f: FilterParams): string {
  return `cursor:${filterHash(f)}`;
}

export async function getCursor(f: FilterParams): Promise<string | null> {
  const v = await get<string>(key(f));
  return v ?? null;
}

export async function saveCursor(f: FilterParams, cursor: string | null): Promise<void> {
  if (cursor === null) await del(key(f));
  else await set(key(f), cursor);
}

export async function clearCursor(f: FilterParams): Promise<void> {
  await del(key(f));
}
