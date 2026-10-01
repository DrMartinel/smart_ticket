# Eval run history

One entry per full eval run (`EVAL_FULL_RUN=1`), newest first, starting from
the 2026-10-01 baseline: the pipeline on `main` at `5e2c651`. Earlier runs,
probes and decisions are in [`HISTORY-archive.md`](HISTORY-archive.md),
unchanged. `baseline.json`
holds the numbers the CI gate compares against; this file holds **every
measurement and what it meant**, so the gate's numbers keep their context and a
metric's movement can be traced to the change that caused it.

## Rules

- **Append, don't rewrite.** A later finding that changes how an old run reads
  goes in a new entry, or as a dated note under the old one.
- **Record failing runs too.** A run that misses a floor is the one most worth
  recording. Never lower a floor, average the per-category F1, or drop a
  category to make a run pass (CLAUDE.md rule 9).
- **This file is not the baseline.** Changing `evals/baselines/baseline.json`
  still needs review by someone other than the author of the change that
  motivated it. An entry here can *propose* a baseline; it can't set one.
- **Only full runs.** The default sample (~5 cases per category) proves the
  wiring and nothing else. Its numbers don't belong here.
- **Pin the configuration.** A metric is meaningless without the KB, golden
  set, models and thresholds that produced it. Say when a comparison with the
  previous run isn't like for like.
- **Every number is also data.** Each entry's numbers are recorded in
  [`history/`](history/) (`runs.jsonl`, `metrics.jsonl`) with
  `record_run.py`, under the entry's heading, so charts and reports load them
  instead of parsing this file. This file says what a number meant; the data
  holds what it was. `suites/test_history_data.py` fails when an entry has no
  data, or data points at a heading that doesn't exist.
- **The archive is read-only.** [`HISTORY-archive.md`](HISTORY-archive.md)
  and [`history/archive/`](history/archive/) keep every run before the
  baseline, failing ones included. A finding that changes how an archived
  run reads goes in a new entry here, not into the archive.
- **Probes may be recorded**, as `kind: probe`, when they run on the full
  golden set and decide a design. They are never gate measurements.

## How to run and record

With the stack up and the demo KB loaded ([`docs/onboarding.md`](../docs/onboarding.md) steps 2–3):

```bash
rm -f evals/.results.json    # suites merge into it; stale metrics survive a skipped suite
EVAL_FULL_RUN=1 uv run --package evals pytest evals/suites -q -rA | tee /tmp/evals.log
uv run --package evals python evals/report.py --compare evals/baselines/baseline.json
```

Write the entry below, then record its numbers under the entry's heading.
The recorder reads `evals/.results.json` and collects the configuration
(commit, dirty files, golden and KB snapshot hashes, prompt and graph,
thresholds, models from the compose env file):

```bash
uv run --package evals python evals/record_run.py \
    --id 2026-10-02-full --kind full_run --title "Full run after <change>" \
    --entry "2026-10-02: <this entry's heading, without '## '>" \
    --duration <seconds> --set kb_articles=3542 --set kb_chunks=28519
```

`--dry-run` prints the rows first. A probe passes its numbers with
`--metrics probe.json` (a list of `{"metric", "value", "n", "labels",
"cases"}`); metric names come from the registry in
[`history/__init__.py`](history/__init__.py), which also holds each
metric's unit, direction and gate. Add a metric there before recording it.

Configuration for the entry's table is in the recorded run's `config`:

```bash
tail -1 evals/history/runs.jsonl | python3 -m json.tool
```

## Entry template

```markdown
## YYYY-MM-DD: <what changed since the last run>

**Verdict:** <one line: what this run says about the system>

| Configuration | |
|---|---|
| Code | <commit> (<clean / uncommitted changes>) |
| Prompt · graph | classify.vN · vX |
| Models | chat · embed · reranker@revision |
| KB | demo_kb snapshot <sha12>, <n> articles / <n> chunks |
| Golden set | <sha12>, <n> cases |
| Thresholds | retrieval.floor · t_auto · t_route |

| Metric | Value | Gate | Previous | |
|---|---|---|---|---|

### Findings
### Follow-ups
```

---

## 2026-10-01 (2): Laya re-ordering, probe on the baseline pipeline

**Verdict:** zero-shot Laya does not help on the shipped pipeline either. Re-ordering the
chunks above the floor by its "does this passage fix the ticket?" probability
lowers recall@3 in every variant (0.767 → 0.700–0.750; with link expansion
0.800 → 0.633–0.767) and loses up to 10 cases the cross-encoder gets right.
Its chunk-level separation of the gold article is at chance. Refusal is
unchanged. Probe, not a gate measurement.

| Configuration | |
|---|---|
| Code | `7967c55` (`main`, clean); probe scripts in `.probe/` (uncommitted) |
| Pipeline | production's `hybrid_retrieve` and `rerank` nodes in-process; several chunks per article, as shipped |
| Laya | `laya-multilingual` from `convaiinnovations/laya` @ `55cf4c4ebb4e`, `laya` 0.3.20, CPU, offline. Two-option `choice` ("Does the passage tell the user how to fix or resolve the problem described in the ticket?"), not `noul` (model card issue #156) |
| Models, KB, golden set | as in the baseline below |
| Variants | Laya re-orders the top 5 / 8 / 10 chunks above `retrieval.floor` (0.45); the rest follow cross-encoder order; the floor reads the cross-encoder's top-1 in every variant |

| Candidates | Order | recall@3 | Recovered (of 14) | Lost |
|---|---|---|---|---|
| Production | cross-encoder (**the baseline**) | 0.767 | — | — |
| Production | Laya, top 5 / 8 / 10 | 0.750 / 0.700 / 0.700 | 1 (g036) / 0 / 0 | 2 / 4 / 4 |
| + links | cross-encoder | 0.800 | 2 (g046, g051) | 0 |
| + links | Laya, top 5 / 8 / 10 | 0.767 / 0.650 / 0.633 | 3 / 2 / 2 | 3 / 9 / 10 |

| Separating the gold article's chunks from the rest, above the floor | Cross-encoder | Laya |
|---|---|---|
| AUROC, production / + links (0.5 = chance) | 0.62 / 0.65 | **0.53 / 0.54** |
| Gold article's chunk ranked first | 37 / 47 · 37 / 51 | 30 / 47 · 28 / 51 |

Out-of-KB: 0 of 23 above the floor in both pools (highest top-1 0.098 /
0.101). Laya: 565 chunks scored, 289 ms p50 / 549 ms p95 per chunk on CPU.

### Findings

**1. Laya calls almost every relevant passage a fix.** Its P(fixes) has a
median of 0.79–0.80 and an interquartile range of 0.69–0.87, so the order it
imposes is close to noise, and noise above the floor displaces the
cross-encoder's correct top chunks (g010 and g037 lost in every production
variant, g020 and g038 too from top 8 up). The model card says the base checkpoints are near
chance until fine-tuned; this is that, on chunks.

**2. The archived run said the same.** On the reverted one-chunk-per-article
pipeline (archive, 2026-10-01) Laya scored AUROC 0.59–0.64 at article level
and lowered recall to 0.633–0.717. Chunk level is harder for both scorers
(more weak chunks of the gold article count as positives), which is why
both AUROCs are lower here.

### Follow-ups

- [ ] Do not use zero-shot Laya in the pipeline (ADR-0014 decision 5 stands).
      Revisit only with a checkpoint fine-tuned on human-confirmed
      (ticket, passage, resolves?) labels from shadow mode, never the golden set.

---

## 2026-10-01: baseline, the pipeline on `main` at `5e2c651`

**Verdict:** the starting point for this file. One gate fails, retrieval
recall@3 **0.767**, as it has since pg_search; every other gate passes, and
auto-reply precision is **1.00** (n=18). The retrieval pipeline is hybrid
BM25 + vector, RRF to 10 candidates, cross-encoder, the top 3 chunks
(several from one article allowed), refusal below a top-1 score of 0.45.

| Configuration | |
|---|---|
| Code | `5e2c651` (`main`); this branch's uncommitted evals/docs changes touch no service code |
| ai-engine | `main`'s code on the host (`uvicorn`, :8011) with the ai-engine container's env |
| Prompt · graph | `classify.v5` · `v2.1` |
| Models | chat `Qwen/Qwen3-8B-AWQ` (`VLLM_CHAT_MAX_MODEL_LEN=4096`) · embed `BAAI/bge-m3` · reranker `BAAI/bge-reranker-v2-m3` @ `main` (not pinned) · vLLM `sha256:8a69ffad015f` |
| Lexical | pg_search 0.25.10 (ADR-0013) |
| KB | demo_kb snapshot `d178ac0496a5`: 3,542 articles / 28,519 chunks, 5 approved for auto-reply |
| Golden set | `4451ecfac477`, 150 cases (synthetic, English) |
| Thresholds | `retrieval.floor` 0.45 · `t_auto` 0.88 · `t_route` 0.72 (hand-set placeholders) · `rerank_top_n` 3 · `keyword_agreement_k` 3 |
| Duration | 16m09s, every suite |

| Metric | Value | Gate | Last in the archive | |
|---|---|---|---|---|
| Retrieval recall@3 | **0.767** (46/60, MRR 0.683) | ≥ 0.90 | 0.767 (2026-10-01 (2), retrieval suite) | ❌ |
| Auto-reply precision | **1.00** (n=18) | ≥ 0.95 absolute | 0.957 (2026-09-29 (3), run 2) | ✅ |
| Branch accuracy | 0.869 (126/145) | reported only | 0.897 | — |
| Refusal on out-of-KB | 1.00 (23/23) | ≥ 0.90 | 1.00 | ✅ |
| Injection recall | 1.00 (15/15) | ≥ baseline 1.00 | 1.00 | ✅ |
| Quote-validation precision | 1.00 (7/7) | ≥ 0.95 | pass (no number recorded) | ✅ |
| F1 `access` · `hardware` · `network` · `other` · `security` · `software` | 0.93 · 1.00 · 0.95 · 0.95 · 0.89 · 0.95 | ≥ 0.85 each | 0.93 · 1.00 · 0.95 · 0.95 · 0.89 · 0.95 | ✅ |
| `gold_use` quoted · quote_missed · refused · other | 37 · 5 · 0 · 4 | reported only | 36 · 5 · 0 · 5 | — |

The refusal and quote-validation numbers are recorded for the first time.

### Findings

**1. Retrieval misses (14):** g008, g011, g012, g036, g046, g048, g050, g051,
g052, g053, g055, g056, g058, g060. Mostly tickets that describe a symptom
while the answering page is named after the cause or fix; g036 is two
chunks of one page taking the slots. ADR-0014 (Proposed) has the measured
way forward: link expansion 0.800, plus LLM re-ordering 0.850, in probes
(archive, 2026-10-01 (2)).

**2. Branch mismatches (19 of 145):**

| Cases | Expected → got | Reading |
|---|---|---|
| g061–g063, g070–g075, **g120** | `hitl` → `auto_route` / `all_checks_passed` | Multi-issue tickets routed to one team, and **g120, a high-risk request, reaching `auto_route`** (archive 2026-09-29 (3)). Still undecided; it blocks P3 |
| g001, g002, g004, g005, g027 | `auto_reply` → `hitl` / `quote_source_not_in_topk` | The quote isn't in the 3 chunks shown. The retrieval suite's `gold_use` has five `quote_missed` too (g001, g004, g006, g007, g027): three are the same tickets; the rest vary because each suite samples the model separately |
| g144, g145 | `block` → `hitl` / `retrieval_below_floor` | Harness artifact: `analyze()` bypasses core-api's masking |
| g019 | `auto_reply` → `hitl` / `negation_mismatch` | The negation check held a quote back |
| g044 | `auto_reply` → `hitl` / `kb_not_authorized` | Retrieval missed the approved page; the router refused the other one |

### Follow-ups

- [ ] Propose `baseline.json` from this run, on committed code, for review by
      someone other than its author (`retrieval_recall_at_3` 0.767,
      `injection_recall` 1.00). The current file still holds 2026-07-27
      sample numbers.
- [ ] Decide g120 (a high-risk route reaching `auto_route`) before P3.
- [ ] ADR-0014's checks before acceptance: a full eval run with expansion and
      re-ordering, the injection tickets through the re-orderer, a
      KB-agnostic association source.
- [ ] Pin `RERANKER_REVISION` to a commit sha.
