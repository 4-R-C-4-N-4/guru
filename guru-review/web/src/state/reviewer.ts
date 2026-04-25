import { get, set } from 'idb-keyval';

const KEY = 'guru-review:reviewer-id';

export async function getReviewerId(): Promise<string | null> {
  const v = await get<string>(KEY);
  return v ?? null;
}

export async function setReviewerId(id: string): Promise<void> {
  await set(KEY, id);
}

export function suggestDeviceName(): string {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return 'ivy-iphone';
  if (/iPad/.test(ua)) return 'ivy-ipad';
  if (/Android/.test(ua)) return 'ivy-android';
  if (/Mac/.test(ua)) return 'ivy-mac';
  return 'ivy-desktop';
}
