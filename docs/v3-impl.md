# Guru v3 — Implementation Strategy

## Document Purpose

Companion to `v3.md`. Breaks the v3 design into a concrete ordered sequence with explicit data-safety checkpoints. The overriding constraint is: **do not lose the ~2K-chunk first-pass tag data.** Everything below is structured so that at every step, a known-good copy of `data/guru.db` exists on disk *before* any modification runs.

Each phase has: preconditions, deliverables, risks, and a checkpoint — a concrete, verifiable state to reach before moving on. If a phase's checkpoint doesn't pass, stop and fix before proceeding.

---

## Phase 0 — Data safety foundation (before anything else)

**Preconditions:** First complete 27B tagging pass has finished. `data/guru.db` contains ~2K tagged chunks.

**Goal:** Make data loss mechanically impossible by turning "the DB" into a reproducible, versioned, multi-location artifact.

**Steps:**

1. Full DB snapshot, timestamped, to a location outside the repo working tree:
   ```
   mkdir -p ~/guru-backups
   sqlite3 data/guru.db ".backup ~/guru-backups/guru-$(date +%Y%m%d-%H%M%S)-pre-v3.db"
   ```
   Use `.backup` (online backup API) rather than `cp` — it handles WAL cleanly. A `cp` on a DB with an active WAL file can produce a corrupt snapshot.

2. Verify the snapshot opens cleanly and contains what it should:
   ```
   sqlite3 ~/guru-backups/guru-*-pre-v3.db \
     "SELECT COUNT(*) FROM staged_tags;
      SELECT COUNT(DISTINCT chunk_id) FROM tagging_progress;
      PRAGMA integrity_check;"
   ```
   Record these three numbers in a file: `~/guru-backups/guru-pre-v3-manifest.txt`. These are your canary values. If they ever change on the live DB without you causing it, something is wrong.

3. Push the snapshot to a second physical location (external drive, separate machine, encrypted cloud bucket — anything that isn't the same SSD). One copy is not a backup.

4. Export the accepted-and-pending tags to a flat JSON file as a format-independent escape hatch:
   ```
   sqlite3 data/guru.db -json \
     "SELECT * FROM staged_tags;
      SELECT * FROM tagging_progress;" \
     > ~/guru-backups/staged-tags-pre-v3.json
   ```
   If SQLite itself ever becomes the problem, this JSON can be replayed into any future schema.

5. Commit the schema (but not the data) to git as of this moment:
   ```
   sqlite3 data/guru.db ".schema" > scripts/schema.current.sql
   git add scripts/schema.current.sql
   git commit -m "snapshot: schema at end of first 27B tagging pass"
   ```

**Checkpoint:** Three locations hold an identical, verified snapshot. A manifest records the canary counts. The schema at this moment is in git. If every subsequent phase catches fire, you can recover to exactly this state.

**Do not proceed to Phase 1 until this checkpoint passes.**

---

## Phase 1 — Provenance migration

**Preconditions:** Phase 0 complete. No active tagging job running.

**Goal:** Add model and prompt-version columns to `staged_tags` and backfill them. This is the schema change most likely to go wrong, so it comes first while the dataset is smallest and the rollback is cleanest.

**Steps:**

1. Create `scripts/migrations/v3_001_provenance.sql`:
   ```sql
   BEGIN TRANSACTION;

   ALTER TABLE staged_tags ADD COLUMN model TEXT;
   ALTER TABLE staged_tags ADD COLUMN prompt_version TEXT;

   UPDATE staged_tags
      SET model = 'qwen3.5-27b',
          prompt_version = 'v1'
    WHERE model IS NULL;

   -- Verify: every row has both fields populated
   SELECT CASE
     WHEN (SELECT COUNT(*) FROM staged_tags WHERE model IS NULL) > 0
       THEN RAISE(ABORT, 'migration failed: null model')
     WHEN (SELECT COUNT(*) FROM staged_tags WHERE prompt_version IS NULL) > 0
       THEN RAISE(ABORT, 'migration failed: null prompt_version')
   END;

   COMMIT;
   ```
   Transaction wrapping is non-negotiable. Either the whole thing applies or nothing does.

2. Dry-run on a **copy** of the DB first:
   ```
   cp data/guru.db /tmp/guru-migration-test.db
   sqlite3 /tmp/guru-migration-test.db < scripts/migrations/v3_001_provenance.sql
   sqlite3 /tmp/guru-migration-test.db \
     "SELECT DISTINCT model, prompt_version FROM staged_tags;
      SELECT COUNT(*) FROM staged_tags;"
   ```
   The first query should return exactly one row: `qwen3.5-27b|v1`. The count should match your pre-migration canary. If either fails, fix the migration script, don't touch the real DB.

3. Apply to the live DB only after the dry-run is clean:
   ```
   sqlite3 data/guru.db ".backup ~/guru-backups/guru-pre-phase1.db"
   sqlite3 data/guru.db < scripts/migrations/v3_001_provenance.sql
   ```

4. Update `guru/prompt.py` to extract `build_prompt()` and add `PROMPT_VERSION = "v1"`.

5. Update `tag_concepts.py` to write `model` and `prompt_version` on every insert. Read `prompt_version` from `guru/prompt.py`, read `model` from the CLI args.

6. Run a smoke test: re-tag a single chunk that's already been tagged. `--resume` should skip it. Remove it from `tagging_progress` manually, re-tag, confirm the new row has both provenance fields populated.

**Checkpoint:** All existing rows show `model='qwen3.5-27b'`, `prompt_version='v1'`. New rows written by `tag_concepts.py` populate both fields automatically. The pre-phase1 backup exists. Row counts match the canary.

---

## Phase 2 — Bench and sample infrastructure (additive, no risk to existing data)

**Preconditions:** Phase 1 complete.

**Goal:** Add the new tables and sampling script. These are purely additive — they create new tables and never modify existing ones. Lowest-risk phase.

**Steps:**

1. Create `scripts/migrations/v3_002_bench_and_sample.sql` with the `bench_runs`, `bench_results`, and `sample_sets` tables from §4.2 and §4.3 of the design doc. All `CREATE TABLE IF NOT EXISTS`. Dry-run on a copy per Phase 1 pattern, then apply.

2. Implement `scripts/sample_chunks.py` in this order:
   - Stratified mode first. This is the simplest and most useful baseline.
   - Persist to `sample_sets`, print the `set_id` on stdout.
   - Validate by generating a small set (N=20) and inspecting the resulting row.
   - Then diversity mode. Reads `chunk_embeddings`, k-means, writes the set.
   - Active mode deferred to Phase 4 — it needs bench runs to exist first.

3. Implement `scripts/bench_tagging.py`:
   - `run` subcommand first. Reads a sample set, calls the tagger, writes to `bench_results`. Never touches `staged_tags`. This isolation is the single most important invariant in the whole phase — triple-check it.
   - `list` subcommand second (trivial, lets you see what runs exist).
   - `compare` subcommand third. Start with presence agreement and unweighted κ to validate the pairwise join logic, then add quadratic-weighted κ, then per-tradition breakdown, then top-10-worst-concepts.
   - `compare --against-accepted` last. Add the hallucinated-tag surfacing as described in §4.2.

4. Self-bench validation — the critical harness-correctness test:
   ```
   python3 scripts/sample_chunks.py --mode stratified --n 50 --label "self-bench-v1"
   # outputs set_id, say 1
   python3 scripts/bench_tagging.py run --label "27B-self-a" --model qwen3.5-27b --sample-set 1
   python3 scripts/bench_tagging.py run --label "27B-self-b" --model qwen3.5-27b --sample-set 1
   python3 scripts/bench_tagging.py compare --run-a 1 --run-b 2
   ```
   Unweighted κ between two runs of the same model should be high (>0.85) at low temperature, and quadratic-weighted κ should be higher still. If it's low, the harness is broken — the model's own disagreement is a ceiling on its disagreement with anything else, so bad self-bench means no valid comparisons downstream.

**Checkpoint:** `sample_sets`, `bench_runs`, `bench_results` exist and populate correctly. Self-bench produces sane κ. The `staged_tags` canary count is unchanged from Phase 1.

---

## Phase 3 — First real comparison

**Preconditions:** Phase 2 complete and self-bench passed.

**Goal:** Produce the first `docs/benchmarks/` report. This is also the first time the harness touches a genuinely different model, so it's the first opportunity to catch harness bugs that self-bench can't.

**Steps:**

1. Generate two sample sets — one stratified (N=200), one diversity (N=200). Record both set_ids.

2. Run Qwen 3.5 27B against both sample sets as the reference. These runs exist already in `staged_tags` — but *not* in `bench_results`, because the bench harness is isolated. Run them through the bench pipeline to get apples-to-apples latency and structure.

3. Run Qwen 3.5 9B against both sample sets.

4. Run `compare` for both (27B-stratified vs. 9B-stratified, then diversity). Produce two markdown reports.

5. Eyeball the reports. Specifically check:
   - Does the top-10-worst-concepts list match your intuition about which concepts are genuinely ambiguous in the corpus?
   - Is per-tradition κ roughly uniform, or does one tradition stand out as particularly bad?
   - Is the 9B's latency advantage real, and is the κ cost acceptable?

**Checkpoint:** Two reports exist. They tell you whether the 9B is a viable workhorse, or whether you stay on the 27B for the second pass. This is the first decision v3 was built to answer.

---

## Phase 4 — Active sampling + review prioritization

**Preconditions:** Phase 3 complete. Phase 3's bench runs are the first input to active sampling.

**Goal:** Close the loop between benchmarking and review — use disagreement to drive what gets reviewed next.

**Steps:**

1. Add active mode to `scripts/sample_chunks.py`. Three strategies (`disagreement`, `low-confidence`, `novelty`) as in §4.3 of the design doc.

2. Update `review_tags.py` to accept a `--sample-set` argument. When passed, only surface chunks in that set. Crucially, the review UI does not display model/provenance info during review — blind review is enforced here, not in the sampler.

3. Generate a `disagreement` sample set over the Phase 3 bench runs. Review the 50-100 most contentious chunks. Write accepted tags back to `staged_tags`.

4. Phase 4 is complete when you have ~500 reviewed accepted tags concentrated on the hard cases. These are disproportionately valuable for fine-tune training signal.

**Checkpoint:** `staged_tags` contains a substantial reviewed subset (`status='accepted'`). The next bench run can use `compare --against-accepted` for the first time.

---

## Phase 5 — Second tagging pass on grown corpus

**Preconditions:** Phase 4 complete. You've added new texts to the corpus since the first pass, or plan to.

**Goal:** Prove the model-swap workflow works end-to-end on new data. This is the steady-state operation v3 was built to enable.

**Steps:**

1. Run `acquire.py` and `chunk.py` for new texts. These add new nodes to `nodes` but touch nothing in `staged_tags` or `tagging_progress`.

2. Run `tag_concepts.py --resume` with whichever model Phase 3 identified as the right workhorse. `--resume` means only the new chunks get tagged. The existing 2K reviewed+pending tags are not recomputed. This is the whole reason the `tagging_progress` table exists.

3. Review new tags. Run a `compare --against-accepted` to see how the current model is doing against the growing reviewed corpus.

**Checkpoint:** The new corpus is tagged. Old tags are untouched. Review proceeds incrementally.

---

## Phase 6 — Optimizations (triggered, not scheduled)

**Preconditions:** First complete run's data has been observed. Specific bottleneck identified.

**Goal:** Implement exactly one of the three §4.5 optimizations, driven by what the data says.

**Decision rule:**
- If GPU utilization during tagging is <80%: implement concurrent slots first. Pure throughput, no accuracy risk.
- If GPU is saturated and LLM call time dominates: implement embedding pre-filter. Biggest single-model speedup.
- If either shows concept-level agreement patterns where whole clusters of concepts are always score=0 for certain traditions: implement tradition-scoped taxonomies. Biggest accuracy lever.

Each implementation follows the Phase 1 pattern: migration on a copy, verify, apply to live with backup. Each gets its own short doc.

**Do not implement more than one optimization at a time.** The goal is to observe each change's effect against the bench harness. Stacking two changes makes it impossible to tell which one helped or hurt.

---

## Phase 7 — Fine-tuning track (deferred, gated on reviewed-tag volume)

**Preconditions:** ≥1500 accepted tags in `staged_tags WHERE status='accepted'`, spread across all traditions.

**Goal:** Produce the first corpus-specific fine-tuned tagger.

**Steps:**

1. Implement `scripts/export_training_data.py`. JSONL output, hold-out configurable per §4.4. Default hold-out: `--holdout-tradition mesopotamian`.

2. Snapshot the DB again before export (Phase 0 pattern) — the accepted tags are now the most valuable artifact in the system and they should have a backup labeled "pre-first-finetune".

3. Run the export. Inspect the JSONL manually for a few lines. Hash the file and record in the model card.

4. Implement `scripts/run_finetune.sh`. QLoRA on Qwen 3.5 8B, rank 16, on the 3090 locally. Expect 8-12 hours.

5. Merge adapter, export GGUF, load into llama.cpp.

6. Bench the fine-tune against the held-out tradition using `compare --against-accepted`. The fine-tune is adopted *only* if it beats the base model on weighted κ against the hold-out set. No exceptions — "it felt better in spot-checks" is not a fine-tune adoption criterion.

**Checkpoint:** Either a validated fine-tune becomes the new workhorse, or the fine-tune is filed as failed-experiment-1 with a written post-mortem. Both are successes.

---

## Backup discipline across all phases

Three rules that apply to every phase:

1. **Before any schema change, snapshot.** `.backup` to `~/guru-backups/guru-pre-<phase>.db`. Cheap and idempotent.

2. **Migrations are transactions.** Every `.sql` file under `scripts/migrations/` starts with `BEGIN TRANSACTION` and ends with `COMMIT`. An aborted migration leaves the DB exactly where it started.

3. **Keep ≥5 snapshots at all times.** After Phase 7, the backup dir should have snapshots for pre-v3, pre-phase1, pre-phase2, pre-phase6-opt, pre-finetune. Don't delete old snapshots just because they feel outdated — disk is cheap, recovery data isn't.

---

## What this strategy is not

- Not a schedule. No dates. Phases advance when their checkpoints pass, not on a calendar.
- Not parallel. Each phase assumes the previous phase's checkpoint. Don't try to build sampling and bench in parallel; the bench harness depends on sample sets existing.
- Not rigid. If Phase 3's first comparison shows the 9B is catastrophically worse than 27B, skip Phase 4 and go straight to Phase 5 with the 27B. The point is a correct ordering of *dependencies*, not a fixed sequence of commits.

The single invariant that must never break: **the current state of `staged_tags` and `tagging_progress` is always recoverable from at least one snapshot outside the repo.** Every phase above is constructed to preserve that.
