import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { ChunkBodyCache } from './chunkBody.js';

// chunk_id "trad.text.NNN" resolves to <corpus>/trad/text/chunks/NNN.toml.
const CHUNK_ID = 'trad.text.001';

function writeChunk(file: string, body: string): void {
  fs.writeFileSync(
    file,
    `[chunk]\nid = "${CHUNK_ID}"\n\n[content]\nbody = ${JSON.stringify(body)}\n`,
  );
}

describe('ChunkBodyCache', () => {
  let corpusDir: string;
  let chunkFile: string;

  beforeEach(() => {
    corpusDir = fs.mkdtempSync(path.join(os.tmpdir(), 'cbc-'));
    const chunkDir = path.join(corpusDir, 'trad', 'text', 'chunks');
    fs.mkdirSync(chunkDir, { recursive: true });
    chunkFile = path.join(chunkDir, '001.toml');
  });

  afterEach(() => {
    fs.rmSync(corpusDir, { recursive: true, force: true });
  });

  it('serves the same parsed entry on repeat reads (cache hit, no re-parse)', () => {
    writeChunk(chunkFile, 'ORIGINAL body');
    const cache = new ChunkBodyCache(corpusDir);
    const first = cache.load(CHUNK_ID);
    const second = cache.load(CHUNK_ID);
    expect(first.body).toBe('ORIGINAL body');
    // Unchanged file → identical cached object is handed back, proving the
    // mtime check did not defeat caching.
    expect(second).toBe(first);
  });

  it('reloads the body after the toml is re-chunked (no stale cache)', () => {
    writeChunk(chunkFile, 'ORIGINAL body');
    const cache = new ChunkBodyCache(corpusDir);
    expect(cache.load(CHUNK_ID).body).toBe('ORIGINAL body');

    // Re-chunk: rewrite the file and stamp a strictly later mtime so the test
    // is deterministic regardless of filesystem timestamp resolution.
    writeChunk(chunkFile, 'REWRITTEN body');
    const later = new Date(Date.now() + 5000);
    fs.utimesSync(chunkFile, later, later);

    // Pre-fix this returned the stale 'ORIGINAL body' from the LRU.
    expect(cache.load(CHUNK_ID).body).toBe('REWRITTEN body');
  });

  it('returns an empty, uncached body for a missing chunk', () => {
    const cache = new ChunkBodyCache(corpusDir);
    expect(cache.load('trad.text.999')).toEqual({ body: '', meta: {} });
    // A later-created file must be picked up (miss was not cached).
    const created = path.join(corpusDir, 'trad', 'text', 'chunks', '999.toml');
    writeChunk(created, 'NOW EXISTS');
    expect(cache.load('trad.text.999').body).toBe('NOW EXISTS');
  });
});
