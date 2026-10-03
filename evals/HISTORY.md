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

## 2026-10-02 (5): Jev as the final reranker with link expansion, full run

**Verdict:** the probe's retrieval gain holds end to end: recall@3 **0.917**
(from 0.767), passing the 0.90 gate for the first time, and branch accuracy
rises to 0.917. But **auto-reply precision fails its hard gate, 0.889
(16/18)**, against 1.00 at baseline. Both false auto-replies are PII test
cases with no `expected_branch`. Only g148 is Jev's doing; g150 auto-replies
1 time in 3 on the baseline pipeline too (finding 2). Not shippable as run.

| Configuration | |
|---|---|
| Code | `c2c12f7` (`main`) + uncommitted ADR-0015 work: `CandidatePoolNode` (link expansion), `JevReranker` as the final reranker, `retrieval.floor_scorer`; 31 dirty files |
| ai-engine | the working tree on the host (`uvicorn`, :8011), container env plus `SECOND_RERANKER_PROVIDER=jev`, `LINK_EXPANSION_ENABLED=true` |
| Jev | `jev-1.13.0`, question `rerank_resolves.v1`, ranks the cross-encoder's top 15 of the pool (`second_rerank_pool`); links: seeds 3, 5 chunks per page, 20 links per seed |
| Prompt · graph | `classify.v5` · `v2.1` (topology changed; `GRAPH_VERSION` not bumped) |
| Models | as the baseline: chat `Qwen/Qwen3-8B-AWQ` (4096) · embed `BAAI/bge-m3` · cross-encoder `BAAI/bge-reranker-v2-m3` @ `main`. `VLLM_CHAT_GPU_UTIL` 0.6, not `.env`'s 0.62 (KV cache only; 0.62 started after embed/rerank froze the host) |
| KB · golden | `d178ac0496a5` 3,542 / 28,519 · `4451ecfac477`, 150 cases |
| Thresholds | **`retrieval.floor` 0.30 on Jev's scale** (`floor_scorer: jev`, a scratch `THRESHOLDS_PATH`, 🔧 the middle of the probe's 0.12-0.48 gap, so chosen from golden-set data) · `t_auto` 0.88 · `t_route` 0.72 (hand-set for the cross-encoder, unchanged) |
| Duration | 21m52s, every suite |

| Metric | Value | Gate | Baseline (2026-10-01) | |
|---|---|---|---|---|
| Retrieval recall@3 | **0.917** (55/60, MRR 0.872) | ≥ 0.90 | 0.767 (MRR 0.683) | ✅ |
| Auto-reply precision | **0.889** (16/18) | ≥ 0.95 absolute | 1.00 (n=18) | ❌ |
| Branch accuracy | 0.917 (133/145) | reported only | 0.869 (126/145) | — |
| Refusal on out-of-KB | 1.00 (23/23) | ≥ 0.90 | 1.00 | ✅ |
| Injection recall | 1.00 (15/15) | ≥ baseline 1.00 | 1.00 | ✅ |
| Quote-validation precision | 1.00 (7/7) | ≥ 0.95 | 1.00 | ✅ |
| F1 `access` · `hardware` · `network` · `other` · `security` · `software` | 0.97 · 0.97 · 1.00 · 0.93 · 0.89 · 1.00 | ≥ 0.85 each | 0.93 · 1.00 · 0.95 · 0.95 · 0.89 · 0.95 | ✅ |
| `gold_use` quoted · quote_missed · refused · other | 40 · 6 · 0 · 9 | reported only | 37 · 5 · 0 · 4 | — |

`report.py --compare` also flags recall@3 against `baseline.json` (1.000):
that file still holds 2026-07-27 sample numbers (baseline entry,
follow-ups), so the comparison that means something is the one above.

### Findings

**1. Retrieval: the probe reproduces.** Still missed: g011, g012, g048,
g055, g056, exactly the five the probe left (entry (4)). Recovered: g008,
g036, g046, g050, g051, g052, g053, g058, g060. Nothing lost.

**2. The two false auto-replies.** Re-run alone, same config:

| Case | Ticket | Top-1 (Jev) | Auto-replied with |
|---|---|---|---|
| g148 | personal email and phone, "I need help resetting my portal password" | 0.92 | `identity-center.resetpassword-accessportal` |
| g150 | "connection error when connecting to the internal server at 10.0.4.22" | 0.75 | `ec2.TroubleshootingInstancesConnecting` |

The other three unlabeled cases (g146, g147, g149) refused below the floor
(0.04 / 0.12 / 0.04). These are PII-masking cases whose truth gives only
`expected_pii_level`. The precision count treats any auto-reply on them as
wrong. Read on its own, g148's answer is plausible; g150's is a guess (an
"internal server" is not evidently an EC2 instance). This harness also
bypasses core-api's masking, as for g144/g145 at baseline, so neither
ticket arrives as it would in production. Whether they should be labeled
is a golden-set decision for a reviewer, not something to settle by
rescoring this run (CLAUDE.md rule 9).

Each re-run 3 times on both pipelines (baseline: a second ai-engine with
Jev and links off, `retrieval.floor` 0.45 on the cross-encoder):

| Case | Baseline: top-1 · outcome | Jev + links: top-1 · outcome |
|---|---|---|
| g148 | 0.188 (below 0.45) · refused 3/3 | 0.92 · auto-reply 2/3 (trust 0.948), once `quote_source_not_in_topk` |
| g150 | 0.613 · **auto-reply 1/3** (trust 0.918), else `trust_below_route_threshold` (0.650) | 0.68-0.73 · auto-reply 3/3 (trust 0.944-0.953) |

Retrieval is deterministic on both; the variation is the LLM's proposal.
The baseline run's 1.00 caught g150 on its HITL side.

**3. Why they pass now.** g148: the cross-encoder scores the password-reset
page 0.188 and the run refuses before the LLM; Jev's "resolves" question
scores it 0.92, because the page does answer the literal request, and the
floor dropped from 0.45 (cross-encoder) to 0.30 (Jev). g150: the same page
at the top on both, but with Jev the LLM proposes the auto-reply every time
rather than 1 in 3. `t_auto` 0.88 was set
for the cross-encoder's `rerank_top1` and margin. Jev's top-1 sits much
higher (median 0.93 on KB-covered tickets, links pool, in the probe), so the trust
score now runs on inputs it was never set for. ADR-0015's "trust scorer
reads `scorer`" follow-up is the place to fix that, not `t_auto`.

Both runs auto-replied 18 tickets, but not the same 18: the correct ones
went from 18 to 16 as well, two false ones taking their place. Jev lost three correct ones, g035
(`trust_below_auto_threshold`), g041 (`quote_source_not_in_topk`), g045
(`kb_not_authorized`), and gained g027.

**4. Branch mismatches (12 of 145)**, against 19 at baseline: g001, g002,
g004, g005, g041, g144 `quote_source_not_in_topk`; g019
`negation_mismatch`; g035 `trust_below_auto_threshold`; g044
`all_checks_passed` but HITL; g045 `kb_not_authorized`; **g120 still
reaches `auto_route`**; g145 `block` → HITL (harness artifact). The
multi-issue group g061-g063 / g070-g075 no longer mismatches.

### Follow-ups

- [ ] Decide labels for g146-g150 (`expected_branch`), reviewed by someone
      other than this change's author.
- [ ] Trust scoring on Jev's scale: core-api reads `RetrievalSignals.scorer`
      and either has Jev coefficients or sends `jev` runs to HITL with a
      `ReasonCode`, before any P3 use.
- [ ] Choose the Jev floor on data other than the golden set (shadow pairs).
- [ ] ADR-0015, the injection suite through Jev with adversarial KB text,
      and a `GRAPH_VERSION` bump for the new topology.
- [ ] Update `docs/onboarding.md` step 2: `VLLM_CHAT_GPU_UTIL=0.55` no
      longer fits (5.71 GiB weights leave 0.22 GiB KV, 0.56 needed), and
      starting vllm-chat after embed/rerank froze a 12 GiB host.

---

## 2026-10-02 (4): Jev re-ordering and ranking, probe on the baseline pipeline

**Verdict:** Jev, TypeSafe's hosted System One model, asked one yes/no
question per chunk ("does the passage tell the user how to fix or resolve the
problem in the ticket?"), is the best ranker measured. Ranking the
cross-encoder's **top 15** of the links pool it reaches recall@3 **0.917**
(9 recovered, **nothing lost**), above the 0.90 gate and the 4B's 0.900, at
0.24 s per request (p50) with every chunk of a ticket sent in parallel. Unlike
Laya, the other System One model measured (entry (2)), it separates the gold
page well (AUROC 0.84 on the links pool). Two things block it: it is a hosted
API outside ADR-0009/0012, and prompt injection is untested. Probe, not a gate
measurement.

| Configuration | |
|---|---|
| Code | `c2c12f7` (`main`); no service code changed since `003f7d3`; probe scripts and data in `.probe/jev/` (gitignored) |
| Pools | built fresh with the stack up (`db`, `vllm-embed`, `vllm-rerank`): production's retrieval code in-process (BM25 + vector, RRF, 10 candidates), every chunk kept, for all 60 KB-covered and 23 out-of-KB tickets; + links: 5 chunks (by cosine) of each page linked from the articles of the cross-encoder's top 3. Link graph 2,928 articles / 14,202 edges; pools 5,617 chunks, median 57 per ticket |
| Jev | `jev-1.13.0` (pinned, not the `jev-latest` alias), `POST api.typesafe.ai/v1/systemone`. One request per (ticket, chunk), state `{ticket: {subject, body}, passage: {title, text}}`, two Nouls in parallel: **resolves**, "Does `passage` tell the user how to fix or resolve the problem described in `ticket`?" with true/false criteria (steps that fix it / related topic, describes the problem, or something else); **relevant**, "Does `passage` address the subject of `ticket`?" (the RAG-passage cookbook's question). Nouls come back with two decimals; ties break in cross-encoder order |
| Variants | as entries (2), 2026-10-02 and (2)-(3): re-orders the top 5 / 8 / 10 chunks above `retrieval.floor` (0.45), the floor reading the cross-encoder's top-1; ranks the whole pool; ranks the cross-encoder's top N of the links pool |
| Models, KB, golden set | as in the baseline below |

The pools reproduce entry 2026-10-02 (2) for the cross-encoder: 0.767 with the
same 14 misses, 0.800 with links (g046, g051), the same lowest KB-covered and
highest out-of-KB top-1 in both pools. The links pool has 178 more chunks than
that entry's (5,439): the link extractor was rewritten (the old one was never
committed) and resolves slightly more links. Comparisons with the 4B on the
links pool are close, not exact.

**1. Recall@3** (recovered and lost against the baseline's 14 misses)

| Candidates | Ranker | recall@3 | Recovered | Lost |
|---|---|---|---|---|
| Baseline | cross-encoder (the baseline) | 0.767 | — | — |
| Baseline | Jev, either question, any variant | 0.783 | 1 (g036) | 0 |
| + links | cross-encoder | 0.800 | 2: g046, g051 | 0 |
| + links | Jev "resolves", top 5 / 8 / 10 above floor | 0.833 / 0.850 / 0.850 | 4 / 5 / 5 | 0 |
| + links | Jev "relevant", top 5 / 8 / 10 above floor | 0.817 / 0.833 / 0.833 | 3 / 4 / 4 | 0 |
| + links | Jev "resolves" ranks CE top 10 | 0.850 | 5 | 0 |
| + links | **Jev "resolves" ranks CE top 15 / 20 / 30 / all** | **0.917** | **9:** g008, g036, g046, g050, g051, g052, g053, g058, g060 | **0** |
| + links | Jev "relevant" ranks CE top 15 / 20 / 30 / all | 0.900 | 8 (not g053) | 0 |
| + links | for comparison: 4B "resolves" ranks CE top 20 (entry (3)) | 0.900 | 8 | 0 |

Still missed by the best variant: g011, g012, g048, g055, g056.

**2. Separating the gold article's chunks, above the floor**

| | Cross-encoder | Jev "resolves" | Jev "relevant" |
|---|---|---|---|
| AUROC, baseline / + links (0.5 = chance) | 0.62 / 0.72 | 0.75 / **0.84** | 0.76 / 0.85 |
| Gold article's chunk ranked first | 38/47 · 38/56 | 42/47 · **51/56** | 42/47 · 47/56 |

**3. Refusal: each ticket's top-1 score when Jev ranks the whole pool**

| Pool | Scorer | KB-covered top-1: lowest / 10th pct / median | Out-of-KB top-1: median / highest | KB refused just above the highest out-of-KB |
|---|---|---|---|---|
| Baseline | Jev "resolves" | 0.04 / 0.53 / 0.91 | 0.01 / 0.12 | 1 (g055) |
| Baseline | Jev "relevant" | 0.67 / 0.94 / 0.97 | 0.02 / 0.34 | 0 |
| + links | Jev "resolves" | 0.48 / 0.71 / 0.93 | 0.01 / 0.12 | 0 |
| + links | Jev "relevant" | 0.76 / 0.95 / 0.97 | 0.02 / 0.34 | 0 |

**4. Checks.** Tie order: breaking ties against cross-encoder order changes no
result above. Repeatability: the 882 pairs of the 14 missed tickets, scored a
second time: 565 "resolves" scores identical, the largest change 0.09; every
"resolves" result is unchanged, while "relevant" gains g056 (whole pool 0.917)
and its top-8 re-order 0.850. The 46 hits were not re-scored.

**5. Cost and time:** 5,617 requests, 3.89 M input tokens, $0.16 at $0.042 per
M; 237 ms p50 / 293 ms p95 per request, 12 in flight, no 429s. Per ticket at
cap 15, the requests run in parallel: under 0.5 s, against 3.1 s for the 4B on
an idle GPU.

### Findings

**1. The question decides it, as with the 4B.** "Resolves" and "relevant"
separate the gold page about equally (AUROC 0.84 / 0.85), but "resolves" puts
it first for 51 of 56 tickets, "relevant" for 47, and only "resolves" lifts
g053. The misses are pages that describe the symptom outranking the page with
the fix; asking for the fix is what moves them.

**2. Zero-shot System One is not one thing.** Laya, asked the same question,
was at chance (AUROC 0.53 / 0.54) and lost up to 10 cases (entry (2)). Jev is
the best scorer measured. ADR-0014 decision 5 is about zero-shot Laya and
stands; it says nothing about Jev.

**3. Its scale may suit the trust signals.** Its "resolves" top-1 to top-2
margin has a median of 0.075 on the baseline pool, against the cross-encoder's
0.009 and the 4B's 0.004, without remapping (Nouls are already 0-1). That says
nothing yet about calibration against `t_auto`/`t_route`.

**4. The refusal gap holds only with links for "resolves".** On the baseline
pool g055 (a GuardDuty backdoor finding) scores 0.04: no page among its 10
candidates resolves it. A floor on "resolves" would refuse it; today's floor,
on the cross-encoder, does not. No floor is chosen here (tuning on the gate).

### Follow-ups

- [ ] A hosted model in the request path: ADR-0009/0012 keep every model
      self-hosted behind ai-engine. Using Jev needs an ADR covering data
      leaving the host (masked ticket text and KB chunks; zero retention is
      enterprise-only), availability and rate limits ("adjusting
      dynamically" per TypeSafe), the fallback when it is down (degrade to the
      cross-encoder order, never skip retrieval), and version pinning.
- [ ] Prompt injection: the 15 injection tickets and adversarial KB text
      through Jev. TypeSafe's own notes (Jev 1.13 jaggedness) say adversarial
      state can move answers.
- [ ] Repeatability over all 60 KB-covered tickets, not only the 14 misses.
- [ ] If those hold: a full eval run with expansion and Jev ranking the
      cross-encoder's top 15 (auto-reply precision, branch accuracy,
      refusal), as ADR-0014 already requires of any re-orderer.

---

## 2026-10-02 (3): Qwen3-Reranker-4B on a capped pool, probe on the baseline pipeline

**Verdict:** the 4B does not need the whole links pool. Ranking only the
cross-encoder's **top 20** chunks, it keeps the full recall@3 **0.900**
(8 recovered, nothing lost) and the clean refusal gap, at **4.0 s per ticket**
(p95 6.7 s) on an idle GPU, against 9.5 s (p95 25 s) for the whole pool.
Retrieval quality and refusal are settled in its favour on this golden set;
GPU memory, the trust signals, prompt injection and a full eval run are not.
Probe, not a gate measurement.

| Configuration | |
|---|---|
| Code | `f590555` (`main`); no service code changed since `003f7d3`; probe scripts in `.probe/` (uncommitted) |
| Data | the pools and 4B scores of entry (2) (5,439 chunks, 83 tickets). The 4B scores each chunk on its own, so a cap changes which chunks it sees, never their scores: recall and the refusal gap per cap are exact from that run |
| Cap | the cross-encoder orders the links pool; the 4B ("resolves", `22e683669bc0`, bf16, fp32 projection) ranks its top N; the top 3 of those go to the model |
| Latency | measured fresh for N = 15 and 20, all 83 tickets, RTX 3060 alone (vLLM servers stopped), batches capped at 8,192 tokens; N = 10 estimated from the per-chunk rate |

| Cap N | recall@3 | Recovered (of 14) | Lost | KB-covered top-1, lowest | Out-of-KB top-1, highest | Per ticket, median / p95 |
|---|---|---|---|---|---|---|
| 10 | 0.867 | 6 | 0 | 1.55 | −2.02 | ≈ 1.8 s (estimated) |
| 15 | 0.883 | 7 (not g011) | 0 | 2.67 | −2.02 | 3.1 / 5.2 s |
| **20** | **0.900** | **8:** g011, g036, g046, g051, g052, g056, g058, g060 | **0** | 2.67 | −2.02 | **4.0 / 6.7 s** |
| 25, 30 | 0.900 | 8 | 0 | 2.67 | −2.02 | not timed |
| all (median 52) | 0.900 | 8 | 0 | 2.67 | −2.02 | 9.5 / 25 s (entry (2)) |

### Findings

**1. 20 is the knee.** Every gold page the 4B can lift into the top 3 is already in the
cross-encoder's top 20; caps above it add time and nothing else. Below it, g011
(cap 15) and g011 and g052 (cap 10) drop out.

**2. The refusal gap does not depend on the cap.** At every cap the out-of-KB tickets
top out at −2.02 and the KB-covered ones start at 1.55 or above, so a floor between
them would refuse no KB-covered ticket. None is chosen here (tuning on the gate).

**3. Latency is now in range, not settled.** 4.0 s per ticket runs in the background
worker, not in front of the user, but it is twice Qwen3-8B's two re-order calls
(2 × 1.2 s, entry 2026-10-01 (3)) and was measured with the GPU to itself.

### Follow-ups

- [ ] An int4 build of the 4B, measured for quality on this probe and for fit beside
      the three vLLM servers (bf16 needs 11.6 GB alone).
- [ ] Prompt injection through the ranker: the 15 injection tickets plus adversarial
      ones, checked for scores pushed over a floor.
- [ ] If both hold: the ADR (scorer and floor calibration superseding ADR-0005's,
      the trust signals on the log-odds scale in both services), then a full eval run.

---

## 2026-10-02 (2): Qwen3-Reranker-4B as the only reranker, probe on the baseline pipeline

**Verdict:** ranking the whole candidate pool itself, in place of the
cross-encoder, the 4B with the "resolves" instruction reaches recall@3
**0.900 with link expansion**, the first time anything meets the 0.90 gate,
with **nothing lost**. A refusal floor exists on its scale: every out-of-KB
ticket's top-1 scores below every KB-covered ticket's, with a wide gap. Two
things block a migration: the trust signals collapse on the 0-1 scale they
require, and scoring the whole links pool takes 9.5 s per ticket on an idle
GPU (25 s at p95). Probe, not a gate measurement; whether to migrate is an ADR
question, not this entry's.

| Configuration | |
|---|---|
| Code | `2cd95de` (`main`); no service code changed since `003f7d3`; probe scripts in `.probe/` (uncommitted) |
| Pools | built fresh with the stack up: production's `hybrid_retrieve` and `rerank` nodes in-process, **every** chunk kept, for all 60 KB-covered and 23 out-of-KB tickets: the 10 candidates (baseline) and + 5 chunks of each page linked from the articles of the cross-encoder's top 3 (links); 5,439 chunks, each with its cross-encoder score |
| Reranker | `Qwen/Qwen3-Reranker-4B` @ `22e683669bc0`, bf16, yes/no projection in fp32, "resolves" instruction (as in entry 2026-10-02), on the RTX 3060 with the vLLM servers stopped; batches capped at 8,192 tokens (16 long chunks ran out of memory) |
| Compared | the cross-encoder (`bge-reranker-v2-m3`) ranking the same pools |

**1. Recall@3, each scorer ranking the whole pool**

| Candidates | Ranker | recall@3 | Recovered (of 14) | Lost |
|---|---|---|---|---|
| Baseline (10 candidates) | cross-encoder (the baseline) | 0.767 | — | — |
| Baseline (10 candidates) | 4B "resolves" | 0.800 | 2: g011, g036 | 0 |
| + links | cross-encoder | 0.800 | 2: g046, g051 | 0 |
| + links | **4B "resolves"** | **0.900** | **8:** g011, g036, g046, g051, g052, g056, g058, g060 | **0** |

**2. Refusal: each ticket's top-1 score, KB-covered (60) against out-of-KB (23)**

| Pool | Scorer | KB-covered top-1: lowest / 10th pct / median | Out-of-KB top-1: median / highest | Separation | KB refused just above the highest out-of-KB |
|---|---|---|---|---|---|
| Baseline | cross-encoder (0-1) | 0.413 / 0.868 / 0.987 | 0.002 / 0.098 | 1.000 | 0 (today's 0.45 floor refuses g056) |
| Baseline | 4B (log-odds) | 1.37 / 3.99 / 7.39 | −7.27 / −2.02 | 1.000 | 0 |
| + links | cross-encoder | 0.632 / 0.868 / 0.988 | 0.003 / 0.101 | 1.000 | 0 |
| + links | 4B | 2.67 / 4.47 / 7.44 | −6.55 / −2.02 | 1.000 | 0 |

**3. Trust signals on the 0-1 wire scale** (KB-covered, baseline pool): the
cross-encoder's `rerank_margin` has a median of 0.009 (90th pct 0.102), its
top-1 is ≥ 0.99 for 26 of 60 tickets. The 4B's, as sigmoid(log-odds): median
margin 0.004 (90th pct 0.033), top-1 ≥ 0.99 for 53 of 60.

**4. Time, idle GPU:** links pool, median 52 chunks per ticket, 9.5 s (p95
25 s), 183 ms per chunk; the baseline's 10 chunks ≈ 1.8 s per ticket.

### Findings

**1. Ranking beats re-ordering.** As the only ranker the 4B reaches 0.900; re-ordering the
cross-encoder's top 8 reached 0.850 (entry 2026-10-02). Seeing the whole pool, it promotes
chunks the cross-encoder ranked 9th or lower: g011 and g052 are recovered by no
earlier variant.

**2. The floor would move, not vanish.** Out-of-KB tickets score negative (median
−7.3), KB-covered ones positive (median 7.4), and the closest pair is 3.4 log-odds apart on the
baseline pool. No floor is chosen here: fitting one to these 83 tickets would
be tuning on the gate. It needs a reviewed calibration, like today's 0.45, which
was hand-set and not fitted either.

**3. The trust signals need redefining, not remapping.** On the 0-1 scale the 4B saturates:
its top-1 is ≥ 0.99 for 53 of 60 tickets and its margin all but disappears.
`rerank_top1` and `rerank_margin` would have to move to the log-odds scale, a
wire-schema change in both services (rule 4) with new trust weights.

**4. Latency rules out the whole links pool.** 9.5 s median per ticket with the GPU
to itself; shared with the chat model, slower. A practical version would have the
4B rank only part of the pool.

### Follow-ups

- [ ] Capped pool: the 4B ranking only the cross-encoder's top 15-20 chunks of the
      links pool, to see how much of the 0.900 survives at a practical latency.
- [ ] Prompt injection through an instruction-following ranker: the 15 injection
      tickets plus adversarial ones, checked for scores pushed over a floor.
- [ ] If those hold: an ADR superseding ADR-0005's calibration (the scorer and
      its floor change, the rule against thresholding the fused score does not),
      the trust-signal redefinition, an int4 build to fit the 12 GB card, then a
      full eval run.

---

## 2026-10-02: Qwen3-Reranker-4B re-ordering, "relevance" and "resolves" instructions, probe on the baseline pipeline

**Verdict:** a reranker trained for the job, asked which passage *resolves*
the ticket, matches the best result so far in a single pass: with link
expansion, recall@3 **0.850** at top 8, the same five cases recovered as
Qwen3-8B with both-orders agreement (entry (3)), **nothing lost**, refusal
unchanged. Its separation of the gold page is the best measured (AUROC 0.81).
With its default "relevance" instruction it reaches 0.833 but loses a case.
Its cost is memory: 11.6 GB of the 12 GB card on its own, in bf16. Probe, not a
gate measurement.

| Configuration | |
|---|---|
| Code | `1679e0f` (`main`); no service code changed since `003f7d3`. Pools reused from entry (2)'s step A (the baseline pipeline's nodes in-process, 565 chunks above the floor) |
| Reranker | `Qwen/Qwen3-Reranker-4B` @ `22e683669bc0`, Apache-2.0, Transformers 5.18 on the RTX 3060 (stack down), bf16 weights, the yes/no projection of the last hidden state in fp32 (bf16 logits had rounded 0.6B scores into ties) |
| Scoring | pointwise, the model card's recipe: its system prompt, `<Instruct>/<Query>/<Document>`, score = yes−no log-odds. Query = ticket subject and body; document = article title and chunk |
| Instructions | **relevance**: the card's default, "Given a web search query, retrieve relevant passages that answer the query" · **resolves**: "Given an IT support ticket, retrieve passages that tell the user how to fix or resolve the problem described in the ticket" |
| Variants | re-orders the top 5 / 8 / 10 chunks above `retrieval.floor` (0.45); the rest follow cross-encoder order; the floor reads the cross-encoder's top-1 throughout |

| Candidates | Order | recall@3 | Recovered (of 14) | Lost |
|---|---|---|---|---|
| Baseline | cross-encoder | 0.767 | — | — |
| Baseline | 4B "relevance", top 5 / 8 / 10 | 0.767 | 1 (g036) | 1 (g031) |
| Baseline | 4B "resolves", top 5 / 8 / 10 | 0.783 | 1 (g036) | 0 |
| + links | cross-encoder | 0.800 | 2: g046, g051 | 0 |
| + links | 4B "relevance", top 5 / 8 / 10 | 0.817 / 0.833 / 0.833 | 4 / 5 / 5 | 1 (g031) |
| + links | **4B "resolves", top 5 / 8 / 10** | 0.833 / **0.850** / 0.850 | 4 / **5** / 5: g036, g046, g051, g058, g060 | **0** |

| Separating the gold article's chunks, above the floor | Cross-encoder | 4B "relevance" | 4B "resolves" |
|---|---|---|---|
| AUROC, baseline / + links (0.5 = chance) | 0.62 / 0.65 | 0.66 / 0.74 | **0.76 / 0.81** |
| Gold article's chunk ranked first | 37/47 · 37/51 | 34/47 · 36/51 | **42/47 · 46/51** |

Out-of-KB: 0 of 23 above the floor in both pools (highest top-1 0.098 /
0.101). Scoring: 565 chunks per instruction in about 100 s, ~0.18 s per
chunk on average in batches of 16; peak GPU memory 11.6 GB.

### Findings

**1. The instruction decides it.** The same weights rank the gold page first
for 46 of 51 tickets when asked for the passage that resolves the ticket, 36
when asked for relevance. "Relevance" is what rerankers are trained on and is
what the cross-encoder already does; "resolves" is the judgement the misses
need.

**2. Same recall as Qwen3-8B, a better shape.** It recovers exactly the cases
the chat model recovers with agreement, but scores each chunk on its own: no
position bias, one pass, no second call, and no 4,096-token prompt holding
eight passages (308 were cut in entry (3)).

**3. The 0.6B is not enough.** Its "resolves" variant (scored the same way,
not recorded as a run) reaches 0.817 and drops g046. Size matters here.

**4. It needs the fix page in the pool**, like every re-orderer measured:
without link expansion the best it does is 0.783.

### Follow-ups

- [ ] Memory: the 4B in bf16 fills the 12 GB card alone, so it cannot sit
      beside the three vLLM servers. Measure a quantized 4B (e.g. AWQ, ~3 GB)
      for the same numbers, or decide which server it replaces.
- [ ] Latency in context: score the 8 chunks of one ticket as one batch on the
      shared GPU, against Qwen3-8B's two calls (2 × 1.2 s p50).
- [ ] ADR-0014: name the re-orderer (this or Qwen3-8B with agreement) once the
      memory question is answered; its acceptance checks still stand.

---

## 2026-10-01 (3): LLM re-ordering (Qwen3-8B), probe on the baseline pipeline

**Verdict:** on its own the LLM re-orderer changes nothing (0.767 in every
variant); on top of link expansion it lifts recall@3 from 0.800 to **0.850**,
kept only where both presentation orders agree, with **nothing lost** and
refusal unchanged. It reproduces the archived run of the same probe on the
same code number for number. Probe, not a gate measurement; this is
ADR-0014's measured path.

| Configuration | |
|---|---|
| Code | `6bb717b` (`main`, clean; no service code changed since `003f7d3`); probe scripts in `.probe/` (uncommitted) |
| Pipeline | production's `hybrid_retrieve` and `rerank` nodes in-process; several chunks per article, as shipped |
| Re-orderer | `Qwen/Qwen3-8B-AWQ` on `vllm-chat` (`VLLM_CHAT_MAX_MODEL_LEN=4096`), temperature 0, thinking off, output an enum of the passage ids shown, checked to be an exact permutation |
| Variants | re-orders the top 5 or 8 chunks above `retrieval.floor` (0.45), shown in cross-encoder order and reversed; `both orders agree` promotes a chunk into the top 3 only if both runs put it there, the rest follow cross-encoder order; the floor reads the cross-encoder's top-1 throughout |
| Models, KB, golden set | as in the baseline below |
| Stack | restarted after a host reboot, vLLM servers one at a time |

| Candidates | Order | recall@3 | Recovered (of 14) | Lost |
|---|---|---|---|---|
| Baseline | cross-encoder | 0.767 | — | — |
| Baseline | Qwen3-8B top 5 or 8, any order | 0.767 | 0–1 | 0–1 |
| + links | cross-encoder | 0.800 | 2: g046, g051 | 0 |
| + links | Qwen3-8B top 5, both orders agree | 0.817 | 3: + g058 | 0 |
| + links | **Qwen3-8B top 8, both orders agree** | **0.850** | 5: + g036, g060 | **0** |
| + links | Qwen3-8B top 8, cross-encoder order / reversed | 0.850 / 0.833 | 5 / 5 | 0 / 1 (g009) |

Out-of-KB: 0 of 23 above the floor in both pools (highest top-1 0.098 /
0.101). LLM: 472 calls, 0 invalid; 1.22 s p50 / 2.15 s p95 per call; 308
passages cut to fit 4,096 tokens. Link expansion reranks a median of 48
chunks per ticket (162 at most), against 10.

### Findings

**1. It needs the fix page in the pool.** Without link expansion the
re-orderer has nothing better to promote: every baseline variant stays at
0.767. Expansion brings the remediation pages in; the cross-encoder ranks
them below the pages that describe the symptom; the LLM, asked which
passage *resolves* the ticket, moves three of them up (g036, g058, g060).

**2. Position bias, removed by agreement.** Its first pick is the same in
both presentation orders for only 28–34 of 59 tickets, and shown reversed it
loses a case (g009, g021). Requiring both orders to agree keeps every gain
and loses nothing, at the cost of two calls per ticket.

**3. Against Laya on the same pipeline (entry (2)):** Laya at top 8 with
links scores 0.650 and loses 9 cases; Qwen3-8B with agreement scores 0.850
and loses none. The generative re-orderer is the one worth building.

**4. Reproducible.** Every recall, recovered and lost case equals the
archived run (archive, 2026-10-01 (2)); only latency differs (1.22 s p50
against 1.39 s).

### Follow-ups

- [ ] ADR-0014's checks before acceptance: a full eval run with expansion and
      re-ordering (auto-reply precision, branch accuracy, refusal), the 15
      injection tickets through the re-orderer, and a KB-agnostic association
      source.
- [ ] A token budget for the re-orderer: 308 passages were cut to fit, and a
      cut can remove the fix text.

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
