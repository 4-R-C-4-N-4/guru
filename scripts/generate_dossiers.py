"""
generate_dossiers.py — the --generate half of build_dossiers.py (G5).

Walks the frozen span plan in DAG order and fills the staging tables:
staged_summaries (l1 / l2; folds only under input_budget>0) and
staged_dossier_fields (structure_entry, summary, context, key_figures,
key_terms, reading_notes). Every node is idempotent: a pending or accepted
row for (unit, model, prompt_version) is skipped, so re-runs resume.

Contract validation follows the tag_concepts.parse_tags pattern:
reject-and-retry up to MAX_ATTEMPTS, then log-skip (the node stays
ungenerated and a later run retries it).

Upstream inputs are ACCEPTED rows only (design §1.3.1): structure/l2 read
accepted L1s, D1/D2 read the accepted L2, notes reads accepted context +
structure. Only --stage l1 (and degenerate-work l2) reads primary chunks.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
import tomllib
from pathlib import Path

from llm import call_llm, parse_json_response, ProviderBusy, ContentBlocked
from chunkers.tokens import count_tokens
from clean_bodies import clean_body

PROJECT_ROOT = Path(__file__).parent.parent
PROMPTS_DIR = PROJECT_ROOT / "prompts" / "dossier"
CORPUS_DIR = PROJECT_ROOT / "corpus"
MANIFEST = PROJECT_ROOT / "sources" / "manifest.toml"

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 3
# L1 template version — bumped v1 -> v2 after campaign-c1 review round 1:
# 5/16 sample failures clustered on COVERAGE (order/proportion) + one GROUND
# role-inversion; v2 strengthens order, proportion, and action-direction rules.
# Bumped v2 -> v3 after the c7 tail review (2026-08-13): 3 GROUND failures in
# 3 works, identical mode — the summary names the work's author/translator
# ("Hall", "Ouspensky", "Taylor") when the name appears nowhere in the input;
# v3 bans naming the author/translator/annotator unless the input names them.
L1_TPL = "l1-v3"
# Compression retry template (todo:b1c8be4c fix 1): on a length-band overrun,
# _attempt feeds the model its own summary back through this instead of
# re-rolling the generation prompt. Keep-all-claims compress; the granularity
# loss is an explicit decision rather than a statistical side effect.
COMPRESS_TPL = "compress-v1"
# todo:6d141319 — provenance marker for L1 rows that took the fold-degradation
# path (generate -> compress -> STILL overrunning -> split + merge). A suffix,
# not a metadata note: review_dossiers.py's --prompt-version sampling filter
# sees it, matching the existing '-manual' convention. NOTE: these rows do NOT
# satisfy the plain l1-v3 skip check or review sweep — D3 straggler re-sweeps
# must pass --prompt-version l1-v3-folded explicitly.
FOLDED_SUFFIX = "-folded"
# structure/l2 bumped v1 -> v2 after phase-A review (2026-07-06): structure
# failures clustered on compression-distortion (blended assignments, loosened
# conditions); l2 failures on skipped members and world-knowledge injection.
# structure bumped v2 -> v3 -> v4 -> v5 in the c7 tail review (2026-08-13),
# one failure family across three rounds: titles importing classificatory or
# genre labels absent from the input ("Restraints and Observances",
# "Elements", "Physiology", "Transmigration", "Parables", "Myth", received
# chapter titles), the same import migrating into the synopsis ("including"
# membership in an unenumerated list), then titles importing content words
# with no input lexeme ("source", "divine", "editorial"). v3 restricts title
# vocabulary to the input, v4 extends the rule to the synopsis, v5 requires
# every title content word to appear in the input or span label and bans
# reproducing doxologies/colophons verbatim.
# CAUTION: no row has yet been generated at v5 — its round's rejects were
# fixed via structure-manual rows. Sample a scoped --work run under v5 and
# review it before any wide regeneration; the 799 spans accepted at v2 are
# all stale to the version-keyed skip check.
STRUCT_TPL = "structure-v5"
L2_TPL = "l2-v2"
# todo:64c54b6c — volume/part L2s; D3 --prompt-version sampling sees the suffix
# the same way it sees l1-v3-folded. The FINAL work L2 stays plain l2-v2 at
# sum:{work_id} so promote/export's exactly-one-L2 invariant is unchanged.
L2_PART_SUFFIX = "-part"
# Conservative join budget vs llama.cpp CTX_SIZE=24576. Leaves room for the
# preamble + template. Hierarchical L2 fires strictly above this; small works
# keep the naive single join. Tests monkeypatch this down.
L2_INPUT_BUDGET = 16_000
# Natural internal structure for The Secret Doctrine (source_url /sd1- vs /sd2-).
# Span-plan labels are "Page N" and c12 interleaves volumes — do NOT cluster
# by consecutive plan order.
VOL_KEYS = {
    "vol-1": "Vol 1 Cosmogenesis",
    "vol-2": "Vol 2 Anthropogenesis",
}
STAGES = ["l1", "structure", "l2", "summary", "context", "figures", "terms", "notes"]
FIELD_OF_STAGE = {
    "structure": "structure_entry", "summary": "summary", "context": "context",
    "figures": "key_figures", "terms": "key_terms", "notes": "reading_notes",
}


# ── template rendering (plain token replacement; templates contain JSON braces
#    so str.format is unusable) ────────────────────────────────────────────────

def render(name: str, **vals) -> str:
    tpl = (PROMPTS_DIR / f"{name}.md").read_text()
    for k, v in vals.items():
        tpl = tpl.replace("{" + k + "}", str(v))
    if re.search(r"\{[a-z_]+\}", tpl.split("OUTPUT")[0]):
        unresolved = re.findall(r"\{[a-z_]+\}", tpl.split("OUTPUT")[0])
        raise ValueError(f"template {name}: unresolved placeholders {unresolved}")
    return tpl


def budget_words(tokens: int) -> int:
    """Convert a token budget into the word-denominated budget the prompt
    states (todo:58612368). Local models cannot self-count tokens — asked
    for "124 tokens" Qwen3.8-27B produced ~2.5x over and burned reasoning
    on token arithmetic — but they handle word budgets fine. Measured
    density on this corpus: ~1.41 tokens/word, so words = tokens / 1.4.
    Validation keeps counting cl100k tokens; only the prompt unit changes.
    """
    return max(60, round(tokens / 1.4))


# ── corpus helpers ────────────────────────────────────────────────────────────

def _chunk_bodies(chunk_ids: list[str]) -> str:
    parts = []
    for cid in chunk_ids:
        trad, text, num = cid.rsplit(".", 2)
        d = tomllib.load(open(CORPUS_DIR / trad / text / "chunks" / f"{num}.toml", "rb"))
        parts.append(clean_body(d["content"]["body"]))  # residual layer, §1.2
    return "\n\n".join(parts)


def _display_meta(tradition_dir: str, text_id: str) -> dict:
    return tomllib.load(open(CORPUS_DIR / tradition_dir / text_id / "metadata.toml", "rb"))


def _manifest_notes(members: tuple[str, ...] | list[str]) -> str:
    manifest = tomllib.load(open(MANIFEST, "rb"))["source"]
    by_id = {s["id"]: s for s in manifest}
    blocks = []
    for m in members:
        if m in by_id and by_id[m].get("notes", "").strip():
            blocks.append(f"[{m}] {by_id[m]['notes'].strip()}")
    return "\n\n".join(blocks) or "(no curator notes)"


# ── contract validators ──────────────────────────────────────────────────────

# Scaffold-leak guard: neither the length band nor the verbatim-echo guard can
# catch a model that reproduces prompt scaffolding, planning text, or markup
# instead of clean output. These markers showed up on ~10% of the STAA L1 batch
# (# Summary / INPUT: / OUTPUT: / INPUT ENDS / <br> / leading --- or *** /
# "Let me write ..."), passing the length-only contract silently. Folding the
# check into the validators turns each into an automatic in-loop reject so
# _attempt regenerates it with corrective feedback.
_SCAFFOLD_MARKERS = re.compile(
    r"#\s*Summary\b|\bINPUT\s*:|\bOUTPUT\s*:|\bINPUT\s+ENDS?\b|</?[a-zA-Z][^>]*>"
    r"|\bLet me (?:write|produce|summariz)|\bhere is (?:the|a) summ",
    re.IGNORECASE,
)


def _v_no_scaffold(text: str, *, prose: bool = False) -> None:
    t = (text or "").strip()
    if _SCAFFOLD_MARKERS.search(t):
        raise ValueError("scaffold/template leak in output")
    if t.startswith(("---", "***", "#")):
        raise ValueError("leading markdown/rule artifact")
    if prose and t[:1].islower():
        raise ValueError("prose starts mid-sentence (lowercase)")


def _v_prose(raw: str, lo: int, hi: int, source: str | None = None) -> str:
    body = raw.strip()
    if not body or body.startswith("```"):
        raise ValueError("empty or fenced output")
    n = count_tokens(body)
    if not (lo * 0.5 <= n <= hi * 2):
        raise ValueError(f"prose length {n} outside sanity band [{lo * 0.5:.0f}, {hi * 2}]")
    # Echo guard: a "summary" that copies the input verbatim is a GROUND
    # failure the length band cannot catch (observed: content-filter dodge on
    # the two blocked spans — the model echoed the passage instead of
    # transforming it). Any 15-word shingle of output found verbatim in the
    # source marks an echo.
    if source:
        words = body.split()
        src = " ".join(source.split())
        starts = list(range(0, max(1, len(words) - 14), 7))
        if len(words) >= 15 and (len(words) - 15) not in starts:
            starts.append(len(words) - 15)  # stride must not skip the tail window
        for i in starts:
            if " ".join(words[i:i + 15]) in src:
                raise ValueError("verbatim echo of input (15-word shingle match)")
    _v_no_scaffold(body, prose=True)
    return body


def _v_body_json(raw: str, allow_null: bool = False) -> dict:
    obj = parse_json_response(raw)
    if not isinstance(obj, dict) or "body" not in obj:
        raise ValueError("expected {\"body\": ...}")
    if obj["body"] is None and not allow_null:
        raise ValueError("body is null")
    if obj["body"] is not None and not str(obj["body"]).strip():
        raise ValueError("body is empty")
    if obj["body"] is not None:
        _v_no_scaffold(str(obj["body"]), prose=True)
    return {"body": obj["body"]}


def _v_structure(raw: str) -> dict:
    obj = parse_json_response(raw)
    if not isinstance(obj, dict) or not obj.get("title") or not obj.get("synopsis"):
        raise ValueError("expected {\"title\", \"synopsis\"}")
    if not (1 <= len(str(obj["title"]).split()) <= 8):
        raise ValueError("title word count out of range")
    _v_no_scaffold(str(obj["title"]))
    _v_no_scaffold(str(obj["synopsis"]), prose=True)
    return {"title": obj["title"], "synopsis": obj["synopsis"]}


def _v_listing(raw: str, key: str, item_keys: tuple[str, ...], max_n: int) -> dict:
    obj = parse_json_response(raw)
    items = obj.get(key) if isinstance(obj, dict) else None
    if not isinstance(items, list) or not (0 < len(items) <= max_n + 2):
        raise ValueError(f"expected {{\"{key}\": [1..{max_n}]}}")
    for it in items:
        if not isinstance(it, dict) or any(k not in it for k in item_keys):
            raise ValueError(f"item missing keys {item_keys}")
        for k in item_keys:
            if isinstance(it[k], str):
                _v_no_scaffold(it[k])
    return {key: items}


# ── DB helpers ────────────────────────────────────────────────────────────────

def _summary_exists(conn, summary_id, model, pv) -> bool:
    return conn.execute(
        "SELECT 1 FROM staged_summaries WHERE summary_id=? AND model=? AND prompt_version=?"
        " AND status IN ('pending','accepted')", (summary_id, model, pv)).fetchone() is not None


def _field_exists(conn, work_id, field, span, model, pv) -> bool:
    return conn.execute(
        "SELECT 1 FROM staged_dossier_fields WHERE work_id=? AND field=?"
        " AND COALESCE(section_span,'')=? AND model=? AND prompt_version=?"
        " AND status IN ('pending','accepted')",
        (work_id, field, span or "", model, pv)).fetchone() is not None


def _accepted_l1s(conn, work_id, span_order: dict | None = None) -> list[sqlite3.Row]:
    """Latest accepted row per summary_id (manual rows outrank any template
    version) — a template bump can leave multiple accepted generations."""
    rows = conn.execute(
        "SELECT * FROM staged_summaries WHERE work_id=? AND level=1 AND status='accepted'"
        " ORDER BY id", (work_id,)).fetchall()
    best: dict[str, sqlite3.Row] = {}
    for r in rows:
        cur = best.get(r["summary_id"])
        r_manual = str(r["prompt_version"]).endswith("-manual")
        c_manual = cur is not None and str(cur["prompt_version"]).endswith("-manual")
        if cur is None or (r_manual and not c_manual) or (r_manual == c_manual and r["id"] > cur["id"]):
            best[r["summary_id"]] = r
    if span_order:
        # plan order, not insertion order: remediated (respun/manual) rows have
        # late ids and would otherwise scramble the L2's joined input
        return sorted(best.values(), key=lambda r: (span_order.get(r["section_span"], 10**9), r["id"]))
    return sorted(best.values(), key=lambda r: r["id"])


def _accepted_l2(conn, work_id) -> sqlite3.Row | None:
    # Pin to the FINAL work L2. Hierarchical volume/part rows are also
    # level=2 (todo:64c54b6c); a bare work_id+level query would hand
    # summary/context the wrong body. Manual rows on sum:{work_id} still
    # outrank any template generation — same preference as _accepted_l1s
    # and the promoter.
    sid = f"sum:{work_id}"
    return conn.execute(
        "SELECT * FROM staged_summaries WHERE summary_id=? AND level=2 AND status='accepted'"
        " ORDER BY (prompt_version LIKE '%-manual') DESC, id DESC LIMIT 1",
        (sid,)).fetchone()


def _join_summaries(rows) -> str:
    return "\n\n".join(f"[{r['section_span']}] {r['body']}" for r in rows)


def _pack_summary_rows(rows, budget: int) -> list[list]:
    """Pack consecutive summary rows so each join stays ≤ budget tokens."""
    batches: list[list] = []
    cur: list = []
    for r in rows:
        trial = cur + [r]
        if cur and count_tokens(_join_summaries(trial)) > budget:
            batches.append(cur)
            cur = [r]
        else:
            cur = trial
    if cur:
        batches.append(cur)
    return batches


def _chunk_source_url(cid: str) -> str:
    try:
        trad, text, num = cid.rsplit(".", 2)
        path = CORPUS_DIR / trad / text / "chunks" / f"{num}.toml"
        if not path.exists():
            return ""
        with open(path, "rb") as f:
            d = tomllib.load(f)
        return d.get("chunk", {}).get("source_url", "") or ""
    except (ValueError, OSError, tomllib.TOMLDecodeError, KeyError):
        return ""


def _structure_key(wp, l1_row) -> str:
    """Volume identity from chunk source_url, not span-plan order."""
    from collections import Counter
    span = next((s for s in wp["spans"] if s["label"] == l1_row["section_span"]), None)
    if span is None:
        return "work"
    keys = []
    for cid in span["chunk_ids"]:
        url = _chunk_source_url(cid)
        if "/sd1-" in url:
            keys.append("vol-1")
        elif "/sd2-" in url:
            keys.append("vol-2")
    if not keys:
        return "work"
    return Counter(keys).most_common(1)[0][0]


def _partition_l1s(wp, l1s) -> list[tuple[str, str, list]]:
    order: list[str] = []
    buckets: dict[str, list] = {}
    for r in l1s:
        key = _structure_key(wp, r)
        if key not in buckets:
            order.append(key)
            buckets[key] = []
        buckets[key].append(r)
    out = []
    for k in order:
        label = VOL_KEYS.get(k, wp["label"])
        out.append((k, label, buckets[k]))
    return out


# ── the generator ─────────────────────────────────────────────────────────────

class Generator:
    def __init__(self, cfg: dict, db_path: Path, plan: dict, limit: int = 0):
        self.cfg = cfg
        self.conn = sqlite3.connect(db_path)
        self.conn.row_factory = sqlite3.Row
        self.plan = plan
        self.limit = limit
        self.calls = 0

    def _llm(self, system: str, prompt: str) -> str:
        if self.limit and self.calls >= self.limit:
            raise LimitReached()
        while True:
            try:
                out = call_llm(provider=self.cfg["provider"], model=self.cfg["model"],
                               system=system, prompt=prompt, max_tokens=8192)
                self.calls += 1
                return out
            except ProviderBusy as e:
                logger.warning(f"provider busy — sleeping {e.retry_after:.0f}s ({e})")
                time.sleep(e.retry_after)

    def _attempt(self, system, prompt, validate, compress_to: int | None = None):
        """Generate with contract-reject retry; on length overrun, compress.

        Fresh retries treat length as a statistical re-roll — same prompt +
        same temperature mostly reproduces the overrun (observed c12:
        28/192 spans log-skipped after 3 identical re-rolls). So after the
        first reject of a LENGTH band, the loop switches to the compression
        path (todo:b1c8be4c fix 1): feed the model its own overrunning
        output back with a keep-all-claims compress instruction. That is
        one cheap deterministic call whose granularity loss is an explicit
        decision, not a re-roll that usually lands in-band by dropping
        detail. Attempt shape becomes: generate -> compress -> give up.

        compress_to: target token budget for the compression pass; required
        for the compress path — validators without a prose budget (structure,
        fields) never trigger it.
        """
        last = None
        blocked = 0
        compressed_from = None
        for i in range(MAX_ATTEMPTS + (1 if compress_to else 0)):
            try:
                if compressed_from is not None and compress_to is not None:
                    raw = self._llm(system, render(
                        COMPRESS_TPL,
                        budget_words=budget_words(compress_to),
                        summary=compressed_from))
                else:
                    raw = self._llm(system, prompt)
            except ContentBlocked as e:
                blocked += 1
                logger.warning(f"  content-blocked (attempt {i + 1}): {e}")
                if blocked >= 2:
                    # deterministic for this input — skip the node, stays
                    # resumable; surfaces in the campaign gap report
                    logger.error("  node skipped: content filter is persistent")
                    return None
                continue
            try:
                out = validate(raw)
                if compressed_from is not None and logger.isEnabledFor(logging.INFO):
                    n = count_tokens(compressed_from)
                    logger.info(f"  compressed {n} -> in-band tokens")
                return out
            except ValueError as e:
                last = e
                logger.warning(f"  contract reject (attempt {i + 1}): {e}")
                # Switch to compression on the first length-band overrun;
                # other rejects keep the corrective-feedback retry.
                if compress_to is not None and "outside sanity band" in str(e) \
                        and compressed_from is None:
                    compressed_from = raw.strip()
                    logger.info(f"  overrun — compressing to ~{compress_to} instead of regenerating")
                    continue
                if compressed_from is not None:
                    # Compression already ran and still violates the contract:
                    # give up rather than loop. Attempt shape stays
                    # generate -> compress -> give up.
                    logger.error(f"  compressed output also rejected: {e}")
                    return None
                prompt = prompt + f"\n\nYour previous output was rejected: {e}. Follow the OUTPUT contract exactly."
        logger.error(f"  giving up after {MAX_ATTEMPTS} attempts: {last}")
        return None

    def _preamble(self, wp) -> str:
        meta = _display_meta(wp["tradition"], wp["spans"][0]["text_id"] if wp["spans"] else wp["work_id"])
        return render("preamble", work_label=wp["label"], tradition_label=meta.get("tradition", wp["tradition"]))

    def _insert_summary(self, summary_id, wp, text_id, level, span, chunk_ids, child_sids, body, pv):
        self.conn.execute(
            "INSERT INTO staged_summaries (summary_id, work_id, text_id, level, section_span,"
            " child_chunk_ids, child_summary_ids, body, token_count, model, prompt_version)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (summary_id, wp["work_id"], text_id, level, span,
             json.dumps(chunk_ids) if chunk_ids else None,
             json.dumps(child_sids) if child_sids else None,
             body, count_tokens(body), self.cfg["model"], pv))
        self.conn.commit()

    def _insert_field(self, wp, field, span, payload, pv):
        self.conn.execute(
            "INSERT INTO staged_dossier_fields (work_id, field, section_span, payload_json,"
            " model, prompt_version) VALUES (?,?,?,?,?,?)",
            (wp["work_id"], field, span, json.dumps(payload, ensure_ascii=False),
             self.cfg["model"], pv))
        self.conn.commit()

    # ---- stages ----

    def stage_l1(self, wp):
        model = self.cfg["model"]
        if wp["degenerate"]:
            # single-span work: one summary staged directly at level 2 under
            # l1-v1 grounding rules (design §1.3.5 degenerate case)
            sid = f"sum:{wp['work_id']}"
            if _summary_exists(self.conn, sid, model, L1_TPL):
                return
            chunk_ids = [c for s in wp["spans"] for c in s["chunk_ids"]]
            tok = sum(s["token_count"] for s in wp["spans"])
            budget = min(350, max(200, tok // 12))
            src = _chunk_bodies(chunk_ids)
            prompt = render(L1_TPL, section_span=wp["label"], work_label=wp["label"],
                            budget_words=budget_words(budget)) + "\n\n---\nINPUT:\n\n" + src
            body = self._attempt(self._preamble(wp), prompt,
                                 lambda r: _v_prose(r, int(budget * 0.8), int(budget * 1.2), src),
                                 compress_to=budget)
            if body:
                self._insert_summary(sid, wp, None if len(set(s["text_id"] for s in wp["spans"])) > 1
                                     else wp["spans"][0]["text_id"], 2, None, chunk_ids, None, body, L1_TPL)
                logger.info(f"  [l1/degenerate→L2] {sid}")
            return
        for s in wp["spans"]:
            sid = f"sum:{s['text_id']}:{s['slug']}"
            # Companion fix (todo:6d141319): a folded row under
            # '{L1_TPL}-folded' does NOT satisfy the plain-l1-v3 exists check —
            # without this second probe, every re-run repeats the full
            # generate->compress->fold sequence for an already-folded span.
            if _summary_exists(self.conn, sid, model, L1_TPL) \
                    or _summary_exists(self.conn, sid, model, L1_TPL + FOLDED_SUFFIX):
                continue
            budget = min(300, max(80, s["token_count"] // 12))
            src = _chunk_bodies(s["chunk_ids"])
            prompt = render(L1_TPL, section_span=s["label"], work_label=wp["label"],
                            budget_words=budget_words(budget)) + "\n\n---\nINPUT:\n\n" + src
            body = self._attempt(self._preamble(wp), prompt,
                                 lambda r: _v_prose(r, int(budget * 0.8), int(budget * 1.2), src),
                                 compress_to=budget)
            if body:
                self._insert_summary(sid, wp, s["text_id"], 1, s["label"],
                                     s["chunk_ids"], None, body, L1_TPL)
                logger.info(f"  [l1] {sid}")
                continue
            # generate -> compress failed outright (todo:6d141319): try the
            # fold path once before leaving the span unstaged.
            self._fold_l1(wp, s, sid)

    def _fold_l1(self, wp, s, sid) -> bool:
        """Fold-path degradation for spans whose generate->compress still
        overruns the band (todo:6d141319). Split at chunk boundaries into N
        sub-batches (N = ceil(overrun / budget)), L1 each, then one merge pass
        through compress-v1's keep-all-claims instruction. Stages under
        '{L1_TPL}-folded' so D3 can see the degraded provenance. One level of
        degradation only: if the merged output still violates the band, give
        up exactly as before — no recursion."""
        from build_dossiers import load_text_chunks, _budget_pack  # noqa: PLC0415

        model = self.cfg["model"]
        folded_pv = L1_TPL + FOLDED_SUFFIX
        if _summary_exists(self.conn, sid, model, folded_pv):
            return True  # already folded — do not repeat generate->compress->fold
        if len(s["chunk_ids"]) < 2:
            return False  # no split point; give up as today

        # Sub-batch count from how far past the band the compressed output
        # landed. The overrun magnitude is not returned by _attempt, so use the
        # span's own density instead — the same ceil formula plan-time folds
        # use (build_dossiers.py), applied to span tokens over the budget the
        # failed single call was given.
        budget = min(300, max(80, s["token_count"] // 12))
        chunks = [c for c in load_text_chunks(wp["tradition"], s["text_id"])
                  if c.id in set(s["chunk_ids"])]
        n = -(-s["token_count"] // budget)  # ceil
        sub_target = s["token_count"] // n
        subs = _budget_pack(s["text_id"], s["label"], chunks, sub_target, synthetic=True)
        preamble = self._preamble(wp)
        sub_summaries = []
        for i, sp in enumerate(subs, 1):
            sub_src = _chunk_bodies(sp.chunk_ids)
            sub_budget = min(300, max(80, sp.token_count // 12))
            sub_prompt = render(L1_TPL, section_span=sp.label,
                                work_label=wp["label"],
                                budget_words=budget_words(sub_budget)) \
                + "\n\n---\nINPUT:\n\n" + sub_src
            body = self._attempt(preamble, sub_prompt,
                                 lambda r: _v_prose(r, int(sub_budget * 0.8),
                                                    int(sub_budget * 1.2), sub_src),
                                 compress_to=sub_budget)
            if body is None:
                logger.error(f"  fold: sub-batch {i}/{len(subs)} failed — giving up for {sid}")
                return False
            sub_summaries.append(f"Part {i}:\n{body}")

        merged = self._attempt(
            preamble,
            render(COMPRESS_TPL, budget_words=budget_words(budget),
                   summary="\n\n".join(sub_summaries)),
            lambda r: _v_prose(r, int(budget * 0.8), int(budget * 1.2),
                               "\n\n".join(sub_summaries)))
        if merged is None:
            logger.error(f"  fold: merged output also rejected — giving up for {sid}")
            return False
        self._insert_summary(sid, wp, s["text_id"], 1, s["label"],
                             s["chunk_ids"], None, merged, folded_pv)
        logger.info(f"  [l1/folded {len(subs)} parts] {sid}")
        return True

    def stage_structure(self, wp):
        if wp["degenerate"]:
            return
        l1s = {r["section_span"]: r for r in _accepted_l1s(self.conn, wp["work_id"])}
        for s in wp["spans"]:
            l1 = l1s.get(s["label"])
            if l1 is None:
                continue  # upstream not accepted yet
            if _field_exists(self.conn, wp["work_id"], "structure_entry", s["label"],
                             self.cfg["model"], STRUCT_TPL):
                continue
            prompt = render(STRUCT_TPL, section_span=s["label"], work_label=wp["label"]) \
                + "\n\n---\nINPUT:\n\n" + l1["body"]
            payload = self._attempt(self._preamble(wp), prompt, _v_structure)
            if payload:
                self._insert_field(wp, "structure_entry", s["label"], payload, STRUCT_TPL)
                logger.info(f"  [structure] {wp['work_id']} / {s['label']}")

    def stage_l2(self, wp):
        if wp["degenerate"]:
            return  # produced by stage_l1
        sid = f"sum:{wp['work_id']}"
        if _summary_exists(self.conn, sid, self.cfg["model"], L2_TPL):
            return
        l1s = _accepted_l1s(self.conn, wp["work_id"], self._span_order(wp))
        if len(l1s) < len(wp["spans"]):
            logger.info(f"  [l2] {wp['work_id']}: {len(l1s)}/{len(wp['spans'])} L1s accepted — deferred")
            return
        joined = _join_summaries(l1s)
        if count_tokens(joined) <= L2_INPUT_BUDGET:
            if self._stage_l2_from(wp, sid, None, l1s, L2_TPL, level=2):
                logger.info(f"  [l2] {sid}")
            return
        # Hierarchical: natural structure first (blavatsky volumes), then
        # budget-pack inside a part that still overflows. Bottom-up in this
        # one stage call — parts are pending, not D3-gated, or the stream
        # re-blocks. Upstream L1s remain the only accepted-row dependency.
        parts = _partition_l1s(wp, l1s)
        child_sids = []
        if len(parts) == 1 and parts[0][0] == "work":
            child_sids = self._l2_budget_tree(wp, "work", wp["label"], l1s)
        else:
            for key, label, rows in parts:
                part_sid = f"sum:{wp['work_id']}:{key}"
                part_pv = L2_TPL + L2_PART_SUFFIX
                if count_tokens(_join_summaries(rows)) <= L2_INPUT_BUDGET:
                    if not _summary_exists(self.conn, part_sid, self.cfg["model"], part_pv):
                        if self._stage_l2_from(wp, part_sid, label, rows, part_pv, level=2):
                            logger.info(f"  [l2/part] {part_sid}")
                else:
                    inner = self._l2_budget_tree(wp, key, label, rows)
                    if not _summary_exists(self.conn, part_sid, self.cfg["model"], part_pv):
                        inner_rows = self._rows_by_ids(inner)
                        if inner_rows and self._stage_l2_from(
                                wp, part_sid, label, inner_rows, part_pv, level=2):
                            logger.info(f"  [l2/part] {part_sid}")
                if _summary_exists(self.conn, part_sid, self.cfg["model"], part_pv):
                    child_sids.append(part_sid)
        if not child_sids:
            return
        part_rows = self._rows_by_ids(child_sids)
        if not part_rows:
            return
        if self._stage_l2_from(wp, sid, None, part_rows, L2_TPL, level=2):
            logger.info(f"  [l2] {sid} from {len(part_rows)} parts")

    def _rows_by_ids(self, sids: list[str]) -> list[sqlite3.Row]:
        out = []
        for sid in sids:
            r = self.conn.execute(
                "SELECT * FROM staged_summaries WHERE summary_id=? AND model=?"
                " AND status IN ('pending','accepted') ORDER BY id DESC LIMIT 1",
                (sid, self.cfg["model"])).fetchone()
            if r is not None:
                out.append(r)
        return out

    def _stage_l2_from(self, wp, sid, span, src_rows, pv, *, level: int) -> bool:
        joined = _join_summaries(src_rows)
        n = count_tokens(joined)
        if n > L2_INPUT_BUDGET:
            logger.error(f"  [l2] refusing over-budget join ({n} tokens) for {sid}")
            return False
        if _summary_exists(self.conn, sid, self.cfg["model"], pv):
            return True
        prompt = render(L2_TPL, work_label=wp["label"]) + "\n\n---\nINPUT:\n\n" + joined
        body = self._attempt(self._preamble(wp), prompt,
                             lambda r: _v_prose(r, 200, 350, joined), compress_to=275)
        if not body:
            return False
        text_ids = {r["text_id"] for r in src_rows if r["text_id"]}
        self._insert_summary(sid, wp, text_ids.pop() if len(text_ids) == 1 else None,
                             level, span, None, [r["summary_id"] for r in src_rows], body, pv)
        return True

    def _l2_budget_tree(self, wp, key: str, label: str, rows) -> list[str]:
        """Pack over-budget consecutive rows into level-0 folds; return child ids."""
        batches = _pack_summary_rows(rows, L2_INPUT_BUDGET)
        if len(batches) == 1:
            # Single row still over budget — generate from it anyway is forbidden;
            # refuse rather than 400 the server. A lone L1 this large is a planner bug.
            if count_tokens(_join_summaries(batches[0])) > L2_INPUT_BUDGET:
                logger.error(f"  [l2] single pack still over budget for {wp['work_id']}/{key}")
                return []
            return [r["summary_id"] for r in batches[0]]
        sids = []
        for i, batch in enumerate(batches, 1):
            fold_sid = f"fold:{wp['work_id']}:{key}:{i}"
            if not _summary_exists(self.conn, fold_sid, self.cfg["model"], "fold-v1"):
                if self._stage_fold(wp, fold_sid, label, batch):
                    logger.info(f"  [l2/fold] {fold_sid}")
            sids.append(fold_sid)
        return sids

    def _stage_fold(self, wp, sid, label, src_rows) -> bool:
        joined = _join_summaries(src_rows)
        n = count_tokens(joined)
        if n > L2_INPUT_BUDGET:
            logger.error(f"  [l2] refusing over-budget fold join ({n} tokens) for {sid}")
            return False
        first = src_rows[0]["section_span"] or ""
        last = src_rows[-1]["section_span"] or ""
        prompt = render("fold-v1", work_label=wp["label"], span_first=first,
                        span_last=last, budget_words=budget_words(275)) \
            + "\n\n---\nINPUT:\n\n" + joined
        body = self._attempt(self._preamble(wp), prompt,
                             lambda r: _v_prose(r, 200, 350, joined), compress_to=275)
        if not body:
            return False
        self._insert_summary(sid, wp, None, 0, label, None,
                             [r["summary_id"] for r in src_rows], body, "fold-v1")
        return True

    def _dossier_field(self, wp, stage, template, build_input, validate):
        field = FIELD_OF_STAGE[stage]
        if _field_exists(self.conn, wp["work_id"], field, None, self.cfg["model"], f"{template}"):
            return
        inp = build_input()
        if inp is None:
            return
        tpl_vals, input_text = inp
        prompt = render(template.rsplit("-", 1)[0] + "-" + template.rsplit("-", 1)[1],
                        work_label=wp["label"], **tpl_vals) + "\n\n---\nINPUT:\n\n" + input_text
        payload = self._attempt(self._preamble(wp), prompt, validate)
        if payload is not None:
            self._insert_field(wp, field, None, payload, template)
            logger.info(f"  [{stage}] {wp['work_id']}")

    def stage_summary(self, wp):
        def build():
            l2 = _accepted_l2(self.conn, wp["work_id"])
            if l2 is None:
                return None
            notes = _manifest_notes(self.plan_members(wp))
            return {}, f"(1) SUMMARY:\n{l2['body']}\n\n(2) CURATOR'S NOTES:\n{notes}"
        self._dossier_field(wp, "summary", "summary-v1", build, _v_body_json)

    def stage_context(self, wp):
        def build():
            l2 = _accepted_l2(self.conn, wp["work_id"])
            if l2 is None:
                return None
            meta = _display_meta(wp["tradition"], self.plan_members(wp)[0])
            notes = _manifest_notes(self.plan_members(wp))
            return ({"translator": meta.get("translator") or "translator unknown"},
                    f"(1) CURATOR'S NOTES:\n{notes}\n\n(2) SUMMARY:\n{l2['body']}")
        self._dossier_field(wp, "context", "context-v1", build, _v_body_json)

    def _span_order(self, wp) -> dict:
        return {sp["label"]: i for i, sp in enumerate(wp["spans"])}

    def stage_figures(self, wp):
        def build():
            l1s = _accepted_l1s(self.conn, wp["work_id"], self._span_order(wp))
            src = l1s if l1s else ([_accepted_l2(self.conn, wp["work_id"])] if _accepted_l2(self.conn, wp["work_id"]) else [])
            if not src:
                return None
            return {}, "\n\n".join(f"[{r['section_span'] or 'whole work'}] {r['body']}" for r in src)
        self._dossier_field(wp, "figures", "figures-v1", build,
                            lambda r: _v_listing(r, "figures", ("name", "role", "gloss"), 10))

    def stage_terms(self, wp):
        def build():
            l1s = _accepted_l1s(self.conn, wp["work_id"], self._span_order(wp))
            src = l1s if l1s else ([_accepted_l2(self.conn, wp["work_id"])] if _accepted_l2(self.conn, wp["work_id"]) else [])
            if not src:
                return None
            return {}, "\n\n".join(f"[{r['section_span'] or 'whole work'}] {r['body']}" for r in src)
        # terms bumped v1 -> v2 -> v3 in the c7 yoga-sutras review (2026-08-13):
        # v2 banned enumerating members of unenumerated lists ("the Rules",
        # "the eight means") after two rejections; the failure then migrated to
        # juxtaposition-fusion (glossing the Three Potencies with attributes of
        # the adjacent "things seen" sutra via the outside guna equation), so
        # v3 requires glossing a term only from statements about that term.
        # v4 (same day): the ban text alone failed a third time; v4 adds a
        # worked negative example and the bare-citation rule. Live version =
        # this call site's literal; 62 works' terms accepted at v1 are stale
        # to the version-keyed skip check, so never run --stage terms unscoped.
        self._dossier_field(wp, "terms", "terms-v4", build,
                            lambda r: _v_listing(r, "terms", ("term", "gloss"), 10))

    def stage_notes(self, wp):
        def build():
            ctx = self.conn.execute(
                "SELECT payload_json FROM staged_dossier_fields WHERE work_id=? AND field='context'"
                " AND status='accepted' ORDER BY id DESC LIMIT 1", (wp["work_id"],)).fetchone()
            entries = self.conn.execute(
                "SELECT section_span, payload_json FROM staged_dossier_fields WHERE work_id=?"
                " AND field='structure_entry' AND status='accepted' ORDER BY id", (wp["work_id"],)).fetchall()
            if ctx is None or (not entries and not wp["degenerate"]):
                return None
            outline = "\n".join(
                f"- {r['section_span']}: {json.loads(r['payload_json'])['title']}" for r in entries) or "(single section)"
            return {}, f"(1) CONTEXT NOTE:\n{json.loads(ctx['payload_json'])['body']}\n\n(2) OUTLINE:\n{outline}"
        self._dossier_field(wp, "notes", "notes-v1", build,
                            lambda r: _v_body_json(r, allow_null=True))

    def plan_members(self, wp) -> list[str]:
        seen = []
        for s in wp["spans"]:
            if s["text_id"] not in seen:
                seen.append(s["text_id"])
        return seen or [wp["work_id"]]

    def run(self, stages: list[str], work_filter: str | None):
        for wp in self.plan["works"]:
            if work_filter and wp["work_id"] != work_filter:
                continue
            if wp["gated_by"]:
                logger.info(f"[skip] {wp['work_id']} gated by {wp['gated_by']}")
                continue
            logger.info(f"== {wp['work_id']} ==")
            for st in stages:
                getattr(self, f"stage_{st}")(wp)


class LimitReached(Exception):
    pass


# ── targeted respin (review remediation, G8 surgery) ─────────────────────────
#
# A respin regenerates ONE summary node whose latest row was rejected in
# review, feeding the reviewer's rejection note back into the prompt as a
# corrective instruction. Respun rows are ordinary pending rows — they go
# back through review, never auto-accepted. Provider/model may be overridden
# per respin (recorded verbatim in `model` — e.g. when the campaign provider
# content-blocks a span). Stubborn spans (repeat failures) should be fixed
# as `-manual` rows instead, which the promoter prefers and respins never
# clobber.

def rejected_targets(conn) -> list[tuple[str, str]]:
    """(summary_id, latest rejection note) for spans with NO pending/accepted
    row — i.e. every row for the span is rejected."""
    rows = conn.execute(
        "SELECT summary_id, MAX(id) mid FROM staged_summaries GROUP BY summary_id"
        " HAVING SUM(CASE WHEN status IN ('pending','accepted') THEN 1 ELSE 0 END) = 0"
    ).fetchall()
    out = []
    for r in rows:
        note = conn.execute("SELECT reviewed_by FROM staged_summaries WHERE id=?",
                            (r["mid"],)).fetchone()["reviewed_by"]
        out.append((r["summary_id"], note or ""))
    return out


def respin(gen: "Generator", summary_id: str, feedback: str = "") -> bool:
    """Regenerate one L1/degenerate-L2 node identified by summary_id."""
    for wp in gen.plan["works"]:
        if wp["gated_by"]:
            continue
        if wp["degenerate"] and summary_id == f"sum:{wp['work_id']}":
            target_wp, span = wp, None
            break
        hit = [s for s in wp["spans"] if f"sum:{s['text_id']}:{s['slug']}" == summary_id]
        if hit:
            target_wp, span = wp, hit[0]
            break
    else:
        logger.error(f"respin: {summary_id} not in plan")
        return False

    addendum = ""
    if feedback:
        addendum = (
            "\n\nA previous attempt at this summary was REJECTED in review for the"
            f" following reason — do not repeat this failure:\n> {feedback}\n"
            "Re-check your output against this specific point before finishing."
        )

    if span is None:
        chunk_ids = [c for sp in target_wp["spans"] for c in sp["chunk_ids"]]
        tok = sum(sp["token_count"] for sp in target_wp["spans"])
        budget = min(350, max(200, tok // 12))
        label, text_id, level = target_wp["label"], None, 2
    else:
        chunk_ids = span["chunk_ids"]
        budget = min(300, max(80, span["token_count"] // 12))
        label, text_id, level = span["label"], span["text_id"], 1

    src = _chunk_bodies(chunk_ids)
    prompt = (render(L1_TPL, section_span=label, work_label=target_wp["label"],
                     budget_words=budget_words(budget)) + addendum
              + "\n\n---\nINPUT:\n\n" + src)
    body = gen._attempt(gen._preamble(target_wp), prompt,
                        lambda r: _v_prose(r, int(budget * 0.8), int(budget * 1.2), src),
                        compress_to=budget)
    if body is None:
        return False
    gen._insert_summary(summary_id, target_wp, text_id, level,
                        label if level == 1 else None, chunk_ids, None, body, L1_TPL)
    logger.info(f"  [respin] {summary_id} ({gen.cfg['model']})")
    return True


def run_generate(args, cfg) -> int:
    plan_path = PROJECT_ROOT / "docs" / "summary" / f"span-plan-{cfg['campaign_id']}.json"
    plan = json.loads(plan_path.read_text())
    stages = [args.stage] if args.stage else STAGES
    stages = [s for s in stages if s in STAGES and s != "fold"]
    gen = Generator(cfg, args.db, plan, limit=args.limit)
    try:
        gen.run(stages, args.work)
    except LimitReached:
        logger.info(f"call limit {args.limit} reached — resumable, re-run to continue")
    logger.info(f"generation calls this run: {gen.calls}")
    return 0
