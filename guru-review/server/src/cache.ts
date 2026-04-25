// 30s server-global count cache. Keyed on a canonical hash of filter params
// (sorted-key JSON serialization). Filter-scoped, not reviewer-scoped.

interface CacheEntry<V> {
  value: V;
  expiresAt: number;
}

export class CountCache {
  private store = new Map<string, CacheEntry<unknown>>();

  constructor(private readonly ttlMs = 30_000) {}

  static keyFor(params: Record<string, unknown>): string {
    const sorted = Object.keys(params)
      .sort()
      .reduce<Record<string, unknown>>((acc, k) => {
        if (params[k] !== undefined && params[k] !== null) acc[k] = params[k];
        return acc;
      }, {});
    return JSON.stringify(sorted);
  }

  get<V>(key: string): V | undefined {
    const e = this.store.get(key);
    if (!e) return undefined;
    if (Date.now() > e.expiresAt) {
      this.store.delete(key);
      return undefined;
    }
    return e.value as V;
  }

  set<V>(key: string, value: V): void {
    this.store.set(key, { value, expiresAt: Date.now() + this.ttlMs });
  }

  clear(): void {
    this.store.clear();
  }
}
