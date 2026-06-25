// Port of guru/corpus.py:resolve_chunk_path (commit 21c5541) with an
// mtime+size-validated LRU cache (re-chunking the toml invalidates the entry).
// chunk_id format: "<TraditionDisplay>.<text_id>.<NNN>".
// Tradition segment is the display name ("Christian Mysticism") while
// directories are snake_case ("christian_mysticism"), so we try both.
import * as fs from 'node:fs';
import * as path from 'node:path';
import { parse as tomlParse } from 'smol-toml';

export function resolveChunkPath(chunkId: string, corpusDir: string): string | null {
  const parts = chunkId.split('.');
  if (parts.length < 3) return null;
  const [rawTrad, textId, seq] = [parts[0], parts[1], parts[2]];
  const candidates = [rawTrad, rawTrad.toLowerCase().replace(/ /g, '_')];
  for (const trad of candidates) {
    const p = path.join(corpusDir, trad, textId, 'chunks', `${seq}.toml`);
    if (fs.existsSync(p)) return p;
  }
  return null;
}

interface CacheEntry {
  body: string;
  meta: Record<string, unknown>;
  // File identity at read time. A cached entry is only reused while the toml's
  // mtime AND size both still match on disk, so a re-chunk (which rewrites the
  // file) is picked up on the next request instead of being served stale.
  mtimeMs: number;
  size: number;
}

class LruCache<K, V> {
  private map = new Map<K, V>();
  constructor(private readonly capacity: number) {}

  get(key: K): V | undefined {
    if (!this.map.has(key)) return undefined;
    const v = this.map.get(key)!;
    this.map.delete(key);
    this.map.set(key, v);
    return v;
  }

  set(key: K, value: V): void {
    if (this.map.has(key)) this.map.delete(key);
    this.map.set(key, value);
    if (this.map.size > this.capacity) {
      const oldest = this.map.keys().next().value;
      if (oldest !== undefined) this.map.delete(oldest);
    }
  }

  clear(): void {
    this.map.clear();
  }
}

export class ChunkBodyCache {
  private cache = new LruCache<string, CacheEntry>(5000);

  constructor(private readonly corpusDir: string) {}

  load(chunkId: string): { body: string; meta: Record<string, unknown> } {
    const file = resolveChunkPath(chunkId, this.corpusDir);
    if (!file) {
      // Missing chunk: don't cache — the file may appear later (e.g. after a
      // re-chunk), and resolveChunkPath is cheap (an existsSync probe).
      return { body: '', meta: {} };
    }
    // stat is ~an order of magnitude cheaper than read + tomlParse, so paying
    // it on every hit keeps the cache's real benefit while guaranteeing the
    // body reflects the current file.
    const stat = fs.statSync(file);
    const cached = this.cache.get(chunkId);
    if (cached && cached.mtimeMs === stat.mtimeMs && cached.size === stat.size) {
      return cached;
    }
    const parsed = tomlParse(fs.readFileSync(file, 'utf8')) as {
      content?: { body?: string };
      chunk?: Record<string, unknown>;
    };
    const entry: CacheEntry = {
      body: parsed?.content?.body ?? '',
      meta: parsed?.chunk ?? {},
      mtimeMs: stat.mtimeMs,
      size: stat.size,
    };
    this.cache.set(chunkId, entry);
    return entry;
  }

  clear(): void {
    this.cache.clear();
  }
}
