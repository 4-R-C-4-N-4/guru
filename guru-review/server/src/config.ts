import * as fs from 'node:fs';
import * as os from 'node:os';
import * as path from 'node:path';
import { z } from 'zod';

const ConfigSchema = z.object({
  guru_root: z.string(),
  db_path: z.string(),
  backup_dir: z.string(),
  keep_backups: z.number().int().positive().default(20),
  port: z.number().int().positive().default(7314),
  host: z.string().default('0.0.0.0'),
  default_reviewer: z.string().default('human'),
  dry_run: z.boolean().default(false),
});

export type Config = z.infer<typeof ConfigSchema>;

function expandHome(p: string): string {
  if (p.startsWith('~/')) return path.join(os.homedir(), p.slice(2));
  if (p === '~') return os.homedir();
  return p;
}

export function loadConfig(configPath?: string): Config {
  const file = configPath ?? process.env.GURU_REVIEW_CONFIG ?? path.join(process.cwd(), 'config.json');
  const raw = fs.readFileSync(file, 'utf8');
  const parsed = ConfigSchema.parse(JSON.parse(raw));
  return {
    ...parsed,
    guru_root: expandHome(parsed.guru_root),
    db_path: expandHome(parsed.db_path),
    backup_dir: expandHome(parsed.backup_dir),
  };
}
