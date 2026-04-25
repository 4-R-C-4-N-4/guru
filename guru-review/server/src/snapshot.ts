import * as fs from 'node:fs';
import * as path from 'node:path';
import Database from 'better-sqlite3';

interface SnapshotResult {
  target: string;
  manifest: string;
  staged_tags: number;
  pending: number;
  accepted: number;
  edges: number;
  nodes: number;
}

export async function takeStartupSnapshot(
  dbPath: string,
  backupDir: string,
  keepBackups: number,
): Promise<SnapshotResult> {
  fs.mkdirSync(backupDir, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, '-');
  const target = path.join(backupDir, `guru-${ts}-pre-session.db`);
  const manifest = `${target}.manifest.json`;

  // Online backup — async because better-sqlite3 streams pages in the background.
  // This is the only async point in the otherwise synchronous server.
  const src = new Database(dbPath, { readonly: true, fileMustExist: true });
  try {
    await src.backup(target);
  } finally {
    src.close();
  }

  // Verify integrity + collect canary counts.
  const verify = new Database(target, { readonly: true });
  let counts: Omit<SnapshotResult, 'target' | 'manifest'>;
  let integrity: string;
  try {
    integrity = verify.pragma('integrity_check', { simple: true }) as string;
    if (integrity !== 'ok') {
      throw new Error(`snapshot integrity_check returned: ${integrity}`);
    }
    counts = collectCanary(verify);
  } finally {
    verify.close();
  }

  fs.writeFileSync(
    manifest,
    JSON.stringify(
      {
        created_at: ts,
        source: dbPath,
        target,
        integrity,
        ...counts,
      },
      null,
      2,
    ),
  );

  pruneOldSnapshots(backupDir, keepBackups);

  return { target, manifest, ...counts };
}

function collectCanary(db: Database.Database): Omit<SnapshotResult, 'target' | 'manifest'> {
  const q = (sql: string): number => (db.prepare(sql).get() as { n: number }).n;
  return {
    staged_tags: q('SELECT COUNT(*) AS n FROM staged_tags'),
    pending: q("SELECT COUNT(*) AS n FROM staged_tags WHERE status='pending'"),
    accepted: q("SELECT COUNT(*) AS n FROM staged_tags WHERE status='accepted'"),
    edges: q('SELECT COUNT(*) AS n FROM edges'),
    nodes: q('SELECT COUNT(*) AS n FROM nodes'),
  };
}

function pruneOldSnapshots(backupDir: string, keep: number): void {
  if (!fs.existsSync(backupDir)) return;
  const candidates = fs
    .readdirSync(backupDir)
    .filter((f) => /^guru-.*-pre-session\.db$/.test(f))
    .map((f) => ({ name: f, full: path.join(backupDir, f), mtime: fs.statSync(path.join(backupDir, f)).mtimeMs }))
    .sort((a, b) => b.mtime - a.mtime);

  for (const c of candidates.slice(keep)) {
    fs.unlinkSync(c.full);
    const manifest = `${c.full}.manifest.json`;
    if (fs.existsSync(manifest)) fs.unlinkSync(manifest);
  }
}
