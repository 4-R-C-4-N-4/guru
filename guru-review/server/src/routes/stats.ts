import { Router } from 'express';
import type Database from 'better-sqlite3';

export function statsRouter(ro: Database.Database): Router {
  const r = Router();

  const totalPending = ro.prepare(
    "SELECT COUNT(*) AS n FROM staged_tags WHERE status='pending'",
  );
  const queuedTotal = ro.prepare(
    'SELECT COUNT(*) AS n FROM review_actions WHERE applied_at IS NULL',
  );
  const queuedByAction = ro.prepare(
    "SELECT action, COUNT(*) AS n FROM review_actions WHERE applied_at IS NULL GROUP BY action",
  );
  // ISO timestamps sort lexicographically; date('now') returns YYYY-MM-DD,
  // which compares correctly against the strftime ISO prefix.
  const appliedToday = ro.prepare(
    "SELECT COUNT(*) AS n FROM review_actions WHERE applied_at >= date('now')",
  );
  const appliedTodayByReviewer = ro.prepare(
    "SELECT reviewer, COUNT(*) AS n FROM review_actions WHERE applied_at >= date('now') GROUP BY reviewer",
  );

  r.get('/stats', (_req, res) => {
    res.json({
      pending_tags: (totalPending.get() as { n: number }).n,
      queued_actions: (queuedTotal.get() as { n: number }).n,
      queued_by_action: (queuedByAction.all() as { action: string; n: number }[]).reduce<
        Record<string, number>
      >((acc, row) => {
        acc[row.action] = row.n;
        return acc;
      }, {}),
      applied_today: (appliedToday.get() as { n: number }).n,
      applied_today_by_reviewer: (
        appliedTodayByReviewer.all() as { reviewer: string; n: number }[]
      ).reduce<Record<string, number>>((acc, row) => {
        acc[row.reviewer] = row.n;
        return acc;
      }, {}),
    });
  });

  return r;
}
