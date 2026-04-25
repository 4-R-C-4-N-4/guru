// Local retry queue for offline POST actions (impl.md P13).
//
// When a POST /api/tags/:id/action fails (offline, 5xx), the action is
// pushed to an IndexedDB-backed queue and retried with exponential
// backoff. Idempotency keys (client_action_id) make retries safe.
//
// On app launch, any persisted actions are replayed before the user
// starts a new session.
import { get, set } from 'idb-keyval';
import type { ActionPayload } from '../api/types';

const KEY = 'guru-review:retry-queue';

interface PendingPost {
  staged_tag_id: number;
  payload: ActionPayload;
  attempts: number;
  next_attempt_at: number; // ms epoch
}

async function load(): Promise<PendingPost[]> {
  return (await get<PendingPost[]>(KEY)) ?? [];
}

async function save(items: PendingPost[]): Promise<void> {
  await set(KEY, items);
}

const BASE_BACKOFF_MS = 2000;
const MAX_BACKOFF_MS = 60_000;

function nextDelay(attempts: number): number {
  return Math.min(BASE_BACKOFF_MS * 2 ** attempts, MAX_BACKOFF_MS);
}

let drainTimer: ReturnType<typeof setTimeout> | null = null;
const subscribers = new Set<(n: number) => void>();

async function notifyCount(): Promise<void> {
  const items = await load();
  for (const fn of subscribers) fn(items.length);
}

export function subscribe(fn: (n: number) => void): () => void {
  subscribers.add(fn);
  void notifyCount();
  return () => {
    subscribers.delete(fn);
  };
}

export async function enqueue(stagedTagId: number, payload: ActionPayload): Promise<void> {
  const items = await load();
  items.push({
    staged_tag_id: stagedTagId,
    payload,
    attempts: 0,
    next_attempt_at: Date.now(),
  });
  await save(items);
  await notifyCount();
  scheduleDrain(0);
}

async function drainOnce(): Promise<void> {
  drainTimer = null;
  const items = await load();
  if (items.length === 0) return;

  const now = Date.now();
  const due = items.filter((i) => i.next_attempt_at <= now);
  if (due.length === 0) {
    const minWait = Math.max(0, Math.min(...items.map((i) => i.next_attempt_at - now)));
    scheduleDrain(minWait);
    return;
  }

  for (const item of due) {
    try {
      const res = await fetch(`/api/tags/${item.staged_tag_id}/action`, {
        method: 'POST',
        headers: { 'content-type': 'application/json' },
        body: JSON.stringify(item.payload),
      });
      if (!res.ok && res.status >= 500) {
        // server error → retry with backoff
        item.attempts++;
        item.next_attempt_at = now + nextDelay(item.attempts);
        continue;
      }
      // 2xx OR 4xx — both terminal. 4xx means malformed payload that won't
      // succeed by retry (e.g. staged_tag deleted). Drop it; the UI may
      // surface a separate error.
      const remaining = (await load()).filter(
        (i) => i.payload.client_action_id !== item.payload.client_action_id,
      );
      await save(remaining);
    } catch {
      // network failure → retry
      item.attempts++;
      item.next_attempt_at = now + nextDelay(item.attempts);
    }
  }

  // Persist updated backoff schedules
  const fresh = await load();
  await save(
    fresh.map((i) => {
      const updated = due.find((d) => d.payload.client_action_id === i.payload.client_action_id);
      return updated ?? i;
    }),
  );
  await notifyCount();

  // Schedule next drain.
  const after = await load();
  if (after.length > 0) {
    const minWait = Math.max(0, Math.min(...after.map((i) => i.next_attempt_at - Date.now())));
    scheduleDrain(minWait);
  }
}

function scheduleDrain(delayMs: number): void {
  if (drainTimer) clearTimeout(drainTimer);
  drainTimer = setTimeout(() => void drainOnce(), Math.max(0, delayMs));
}

// On module import (app load), kick off a drain attempt immediately.
if (typeof window !== 'undefined') {
  void notifyCount();
  scheduleDrain(0);
  // Re-drain whenever the browser regains connectivity.
  window.addEventListener('online', () => scheduleDrain(0));
}
