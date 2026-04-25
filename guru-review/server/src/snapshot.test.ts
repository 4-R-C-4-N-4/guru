import { describe, expect, it, beforeEach, afterEach } from 'vitest';
import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import Database from 'better-sqlite3';
import { takeStartupSnapshot } from './snapshot.js';

let workdir: string;
let dbPath: string;
let backupDir: string;

beforeEach(() => {
  workdir = fs.mkdtempSync(path.join(os.tmpdir(), 'guru-review-snap-'));
  dbPath = path.join(workdir, 'src.db');
  backupDir = path.join(workdir, 'backups');

  const db = new Database(dbPath);
  db.exec(`
    CREATE TABLE staged_tags (id INTEGER PRIMARY KEY, status TEXT, chunk_id TEXT);
    CREATE TABLE edges (id INTEGER PRIMARY KEY);
    CREATE TABLE nodes (id INTEGER PRIMARY KEY);
    INSERT INTO staged_tags(id, status, chunk_id) VALUES (1, 'pending', 'a.b.001'), (2, 'accepted', 'a.b.002');
    INSERT INTO edges(id) VALUES (1), (2), (3);
    INSERT INTO nodes(id) VALUES (1), (2), (3), (4);
  `);
  db.close();
});

afterEach(() => {
  fs.rmSync(workdir, { recursive: true, force: true });
});

describe('takeStartupSnapshot', () => {
  it('writes a backup file and a manifest', async () => {
    const result = await takeStartupSnapshot(dbPath, backupDir, 5);
    expect(fs.existsSync(result.target)).toBe(true);
    expect(fs.existsSync(result.manifest)).toBe(true);
    const manifest = JSON.parse(fs.readFileSync(result.manifest, 'utf8'));
    expect(manifest.integrity).toBe('ok');
    expect(manifest.staged_tags).toBe(2);
    expect(manifest.pending).toBe(1);
    expect(manifest.accepted).toBe(1);
    expect(manifest.edges).toBe(3);
    expect(manifest.nodes).toBe(4);
  });

  it('throws when source DB does not exist', async () => {
    await expect(takeStartupSnapshot(path.join(workdir, 'nope.db'), backupDir, 5)).rejects.toThrow();
  });

  it('throws when integrity check fails (corrupt source)', async () => {
    // Overwrite header bytes with garbage to trigger integrity_check failure.
    const fd = fs.openSync(dbPath, 'r+');
    fs.writeSync(fd, Buffer.from('garbage'), 0, 7, 100);
    fs.closeSync(fd);
    await expect(takeStartupSnapshot(dbPath, backupDir, 5)).rejects.toThrow();
  });

  it('prunes oldest snapshots beyond keep limit', async () => {
    // Create 4 stale snapshot files with sequential mtimes
    fs.mkdirSync(backupDir, { recursive: true });
    for (let i = 0; i < 4; i++) {
      const stale = path.join(backupDir, `guru-stale-${i}-pre-session.db`);
      fs.writeFileSync(stale, '');
      fs.writeFileSync(`${stale}.manifest.json`, '{}');
      const t = (Date.now() - (4 - i) * 10000) / 1000;
      fs.utimesSync(stale, t, t);
    }
    // Keep only 2; the new snapshot + 1 stale should survive
    await takeStartupSnapshot(dbPath, backupDir, 2);
    const surviving = fs.readdirSync(backupDir).filter((f) => f.endsWith('.db'));
    expect(surviving.length).toBe(2);
  });
});
