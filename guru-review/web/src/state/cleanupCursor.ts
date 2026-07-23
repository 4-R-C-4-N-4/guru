// Per-device cursor persistence for the cleanup deck. Mirrors
// state/edgeCursor.ts but keyed under `cleanupcursor:` so the three decks
// resume independently.
import { get, set, del } from 'idb-keyval';
import type { CleanupFilterParams } from '../api/types';

function filterHash(f: CleanupFilterParams): string {
  const sorted = Object.keys(f)
    .filter((k) => {
      const v = f[k as keyof CleanupFilterParams];
      return v !== undefined && v !== '' && v !== null;
    })
    .sort()
    .reduce<Record<string, unknown>>((acc, k) => {
      acc[k] = f[k as keyof CleanupFilterParams];
      return acc;
    }, {});
  return JSON.stringify(sorted);
}

function key(f: CleanupFilterParams): string {
  return `cleanupcursor:${filterHash(f)}`;
}

export async function getCleanupCursor(f: CleanupFilterParams): Promise<number | null> {
  const v = await get<number>(key(f));
  return typeof v === 'number' ? v : null;
}

export async function saveCleanupCursor(f: CleanupFilterParams, cursor: number | null): Promise<void> {
  if (cursor === null) await del(key(f));
  else await set(key(f), cursor);
}
