# <source-id> — ingest decisions

One file per text. Append as you go; do not rewrite history when a later node
contradicts an earlier one — record the contradiction and what it cost.

The ledger in `data/ingest/<source-id>.json` records *that* a judgement was
made. This file records *why*. A year from now nobody will ask which chunking
strategy was chosen — that is in the config. They will ask why the obvious one
was rejected, and that answer exists only if it was written down at the time.

---

## 01 — source-vetting · YYYY-MM-DD · <who>

**Verdict:** verified | wrong-page | apparatus | insufficient-evidence

**URL:** <final url, and the original if it was corrected>

**Heading chain read:** <what the page actually said>

**Pagination:** single | multi (<n> pages) — <evidence>

**Licence:** <status and positive evidence>

**Notes:** <anything nodes 02–05 will need>

---

## 04 — boilerplate-survey · YYYY-MM-DD · <who>

**Classes found:** <P1 ×3, P5, …>

**Proposed strips:** <rule, granularity, risk>

**Left alone:** <what looked like boilerplate and is not, and why>

---

## 05 — chunk-config · YYYY-MM-DD · <who>

**Strategy:** <canonical name>

**Why this fits the text's own divisions:** <…>

**Rejected:**

| Strategy | Why not |
|---|---|
| <…> | <…> |

**Expected chunk count:** <n> · **Actual:** <n>

---

## 07 — clean-bodies · YYYY-MM-DD · <who>

**Applied:** <classes> · **Chunks touched:** <n>

**Anything the dry run showed that was not expected:** <…>

---

## 08 — readability-gate · YYYY-MM-DD · <who>

**Verdict:** pass | fix | escalate

**Signals, and whether each read as apparatus or breakage:** <…>

---

## 11 / 14 — review · YYYY-MM-DD · <who>

**Judged:** <n> of <n> · **Queued:** <accepts / rejects / reassigns / skips>

**Patterns worth carrying into the contract:** <…>

**Anything that belongs in a node file's Failure modes:** <…>
