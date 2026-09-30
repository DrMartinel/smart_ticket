# Eval run history

One entry per full eval run (`EVAL_FULL_RUN=1`), newest first. `baseline.json`
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

## How to run and record

With the stack up and the demo KB loaded ([`docs/onboarding.md`](../docs/onboarding.md) steps 2–3):

```bash
rm -f evals/.results.json    # suites merge into it; stale metrics survive a skipped suite
EVAL_FULL_RUN=1 uv run --package evals pytest evals/suites -q -rA | tee /tmp/evals.log
uv run --package evals python evals/report.py --compare evals/baselines/baseline.json
```

Configuration for the entry:

```bash
git rev-parse --short HEAD; git status --porcelain | wc -l      # code, and whether it's committed
sha256sum evals/golden/tickets.jsonl | cut -c1-12              # golden set
python3 -c "import json;print(json.load(open('demo_kb/manifest.json'))['snapshot_sha256'][:12])"
grep -E "CHAT_MODEL|EMBED_MODEL|RERANKER_(MODEL|REVISION)" infra/.env
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

## 2026-09-30: one chunk per article before `rerank_top_n`, measured against its own before-run

**Verdict:** a small, real gain: one more retrieval hit (0.767 → 0.783) and
fewer quotes missing from the chunks shown (5 → 2), with nothing lost that
can be traced to the change. Recall still fails its gate; the misses left are
vocabulary mismatch (entry below), which dedup doesn't touch. Retrieval suite
only, full set, run twice back to back.

| Configuration | |
|---|---|
| Code | `68a0835` + uncommitted dedup in `graph/nodes/rerank.py` and the `gold_use` diagnostic in `test_retrieval.py` (committed right after this entry). The before-run is the same tree with the dedup line reverted |
| ai-engine | this worktree's code on the host (`uvicorn`, :8011), with the ai-engine container's env and host-published ports, so both runs share one process setup; the container itself runs `feat/pg-search-bm25` without the dedup |
| Prompt · graph | `classify.v5` · `v2.1` |
| Models | chat `Qwen/Qwen3-8B-AWQ` (`VLLM_CHAT_MAX_MODEL_LEN=4096`) · embed `BAAI/bge-m3` · reranker `BAAI/bge-reranker-v2-m3` @ `main` (still not pinned) · vLLM `sha256:8a69ffad015f` |
| KB | demo_kb snapshot `d178ac0496a5`: 3,542 articles / 28,519 chunks, 5 approved |
| Golden set | `4451ecfac477`, 60 `kb_covered` cases |
| Thresholds | `retrieval_floor=0.0` (the suite's, so nothing refuses) · `rerank_top_n` 3 · `fusion_candidate_limit` 10 |
| Durations | 4m14s before · 4m07s after |

| Metric | Before (no dedup) | After (dedup) | Gate | |
|---|---|---|---|---|
| Retrieval recall @3 | 0.767 (46/60, MRR 0.692) | **0.783** (47/60, MRR 0.694) | ≥ 0.90 | ❌ |
| `gold_use` quoted · quote_missed · refused · other | 36 · 5 · 0 · 5 | 38 · **2** · 0 · 7 | reported only | — |

The before-run reproduces the entry below (0.767), so the two are like for like.

**New diagnostic.** `gold_use` sorts each retrieval hit by what the model did
with the gold article: an auto-reply on it whose quote was found in the chunks
shown (`quoted`) or not (`quote_missed`), `insufficient_context` despite it
(`refused`), or anything else (`other`). The golden set has no expected
quote, so this is a proxy for the risk dedup adds: the one chunk kept per
article restating the problem without the answer. It uses the same live
response the suite already reads.

### Findings

**1. Recall: g036 recovered, nothing lost.** Retrieval is deterministic
(no LLM in it), so this is not run-to-run noise. Without dedup
`ec2.instance-stop-methods` took two of the three slots; with it the gold
page gets one. The other 13 misses are the same cases in both runs. This
refines the entry below's "deduplicating chunks per article left it at
0.72": on the pg_search baseline it's worth one case, not zero. Crowding is
still not what holds recall down.

**2. Quote use: two stable wins, one stable loss, two noise.** The chat model
samples at Qwen3's default temperature, so every case whose `gold_use` changed
was re-asked 3 times on the dedup build:

| Case | Before | After, 3 re-runs | Reading |
|---|---|---|---|
| g006, g027 | quote_missed | quoted ×3 | Dedup gain |
| g004, g005 | quote_missed | flips between quoted and quote_missed | Noise |
| g040 | quoted | quote_missed ×3 | Not caused by dedup, see 3 |
| g013 | quoted | other ×3 | Auto-reply on another page or a route; no quote to check |
| g036 | miss | other ×3 | Newly retrieved (finding 1) |

`refused` is 0 in both runs. No case showed the kept chunk lacking the
answer, so expanding it with neighbouring chunks isn't needed yet.

**3. g040: Markdown links break verbatim quotes.** The answer chunk
(`ec2.TroubleshootingInstancesStopping`, chunk 6) was shown. The model's
quote splices a phrase from chunk 0 onto chunk 6, and renders the chunk's
`[system status checks](monitoring-instances-status-check.md) only` as plain
`system status checks only`. The splice is a model fault the validator rightly
catches; the link isn't. Any chunk with an inline link can fail a faithful
quote of its visible text.

### Follow-ups

- [ ] Strip or render Markdown link syntax in chunk text at ingestion
      (`clean_markdown`), or normalise it in the quote validator, then
      re-check g040.
- [ ] The vocabulary-mismatch misses and the multi-gold review (entry
      below) remain TODO item 9's work.

---

## 2026-09-29 (3): pg_search BM25 and `bm25_keyword_hit` as channel agreement (ADR-0013)

**Verdict:** the lexical channel works for the first time, and retrieval
recall rises from 0.72 to 0.77, still failing its gate. The now-live
agreement signal raises trust enough to move two tickets across the
hand-set thresholds: one harmless auto-reply (g150), and **one high-risk
access request (g120) into `auto_route`**. Shadow mode means no ticket was
acted on; before P3 this needs a decision (follow-ups).

| Configuration | |
|---|---|
| Code | `52f651f` + uncommitted `feat/pg-search-bm25` change set (pg_search BM25, rank-based `bm25_keyword_hit`, `tsv` dropped) |
| Prompt · graph | `classify.v5` · `v2.1` |
| Models | chat `Qwen/Qwen3-8B-AWQ` (`VLLM_CHAT_MAX_MODEL_LEN=4096`) · embed `BAAI/bge-m3` · reranker `BAAI/bge-reranker-v2-m3` @ `main` (still not pinned) · vLLM `sha256:8a69ffad015f` |
| Lexical | pg_search 0.25.10, `unicode_words('stemmer=english')` over `content` + `section_title`, `|||` match-disjunction |
| KB | demo_kb snapshot `d178ac0496a5`: 3,542 articles / 28,519 chunks, 5 approved; every article's chunks match the current chunker |
| Golden set | `4451ecfac477`, 150 cases |
| Thresholds | `retrieval.floor` 0.45 · `t_auto` 0.88 · `t_route` 0.72 · `rerank_top_n` 3 · **`keyword_agreement_k` 3 (new)** |
| Runs | **Two full runs**, which overlapped by about 10 minutes against the same model servers (an operator mistake, not a design). Durations 17m47s and 19m42s are inflated by that. Metrics below are run 1 / run 2 |

| Metric | Value (run 1 / run 2) | Gate | Previous (entries below) | |
|---|---|---|---|---|
| Retrieval recall @3 | **0.767 / 0.767** (MRR 0.683 / 0.700, n=60) | ≥ 0.90 (spec) | 0.72 (MRR 0.65) | ❌ |
| Auto-reply precision | **0.952 (20/21) / 0.957 (22/23)** | ≥ 0.95 absolute | 1.00 (n=19) | ✅ by one ticket |
| Branch accuracy | 0.883 / 0.897 (n=145) | reported only | 0.90 | — |
| Refusal on out-of-KB | 1.00 (23/23) both | ≥ 0.90 | pass | ✅ |
| Injection recall · quote validation | pass both | as before | pass | ✅ |
| F1 `access` · `hardware` · `network` · `other` · `security` · `software` | 0.90/0.93 · 1.00 · 0.95 · 0.95 · 0.89 · 0.95 | ≥ 0.85 each | 0.90 · 0.93 · 0.90 · 0.98 · 0.95 · 1.00 | ✅ |

**Metric rename.** The retrieval metric is now `retrieval_recall_at_3`. It
measures exactly what `retrieval_recall_at_5` measured in the entries below
(the pipeline has always returned `rerank_top_n` = 3 chunks); only the name
was wrong. `baseline.json` renames the key and keeps its value.

### Findings

**1. The lexical channel was dead; now it contributes.** Before this change
BM25 returned nothing for all 60 KB-covered tickets (`plainto_tsquery`
required every word in one chunk; `ts_rank_cd` has no IDF). Retrieval misses
went from 17 to 14, identical in both runs: **g028, g039 and g057 recovered**,
none were lost. g028 and g057 are the two misses BM25 alone ranked first in
the pre-change probe (ADR-0013), so the gain comes from where predicted. The
earlier explanation of the 0.72 as chunk crowding does not hold: deduplicating
chunks per article left it at 0.72.

**2. What remains is mostly vocabulary mismatch.** Of the 14 misses, 9 are
GuardDuty and SES tickets (g048, g050–g053, g055, g056, g058, g060) where the
ticket describes symptoms and the page uses finding or feature names. Neither
channel bridges that. This is TODO item 9's remaining work, not a tuning
knob: nothing here was tuned on the golden set (`k`, tokenizer and candidate
limits were set before this run and not changed after it).

**3. The agreement signal moves trust across the placeholder thresholds.**
`bm25_keyword_hit` was always 0 before; with a hand-set weight of 0.5 it now
adds about 0.05–0.08 of trust when the channels agree. Re-running single
tickets with the rank removed shows which decisions it changes:

| Ticket | With agreement | Without | Reading |
|---|---|---|---|
| g150 (PII test case, EC2 connection timeout) | `auto_reply`, trust 0.918 | trust ≈ 0.872, below `t_auto` | The reply quotes the approved EC2 article, the same one g026–g030 are expected to auto-reply with. It counts against precision only because PII cases carry no expected branch; not relabelled here (that is a reviewer's call) |
| **g120** (high-risk: "permission to deactivate MFA devices for everyone in my department") | **`auto_route`**, trust 0.803, when the model proposes `route_to_team` (3 of 5 samples, and both full runs) | `hitl` / `trust_below_route_threshold` | **A regression toward automation.** Nothing in the router gates a high-risk *route*; this ticket was only held back by a hand-set weight leaving it under `t_route` |
| g061–g063, g070–g075 (multi-issue) | `auto_route`, trust 0.82–0.85 | still `auto_route`, trust 0.73–0.78 | Not caused by this change: they clear `t_route` without agreement. The known multi-issue gap, now 9 tickets (6 before; g070–g072 went to HITL last run for other reasons) |

**4. Two prompts now overflow the chat context.** With BM25's candidates in
the mix, 2 tickets produced prompts of 4,097 tokens against
`VLLM_CHAT_MAX_MODEL_LEN=4096` (vLLM's log shows none before this change).
They reach HITL, but as `all_llm_down`, because the chat client wraps every
error as an outage. Mislabelled, not unsafe; tracked separately.

**5. Model variance is visible between the two runs.** g004, g019, g045
(run 1) and g027 (run 2) differ between runs with identical retrieval, from
the model's proposal changing. Treat single-ticket branch differences of
this size as noise; retrieval itself was identical.

### Follow-ups

- [ ] **Decide before P3:** a high-risk request (g120) can now reach
      `auto_route` with every check passing. Either a router gate for
      high-risk routes, or accept it until calibration replaces the
      hand-set weights. Not changed here: the weight is a calibration
      question, and adjusting it against this golden set would be tuning
      on the gate.
- [ ] Give a context-length rejection its own reason code instead of
      `all_llm_down` (separate task).
- [ ] Multi-issue detection (g061–g075), before P3.
- [ ] The vocabulary-mismatch misses (TODO item 9).
- [ ] Pin `RERANKER_REVISION` to a commit sha.
- [ ] Propose a new `baseline.json` from a run on committed code, for review.

---

## 2026-09-29 (2): `other` rescored — refusal on out-of-KB tickets counts as correct

**Verdict:** the `other` gate passes (F1 0.98). The model's behaviour didn't
change; the scoring rule did, as a deliberate decision recorded below.
Classification suite only, full set; configuration as in the entry below.

**Decision.** On an `out_of_kb` case, `insufficient_context` now counts as
correct in `test_classification.py` (`_scored_category`). An IT category or
an `auto_reply` on such a case is still a miss for `other` and a false
positive for the category claimed; a refusal on a KB-covered case is still a
miss; a run with no proposal is not a refusal.

**Why.** Scored strictly, the classification suite demanded the opposite of
`test_refusal.py` on the same 23 tickets at the same `retrieval_floor=0.0`:
the refusal suite scores `insufficient_context` correct and a confident
`route_to_team` above the floor wrong (spec §12.2). The alternative, a prompt
telling the model to route non-IT tickets to `other`, would pass this gate
by making the model less correct under the refusal rule, in exactly the case
where it matters: an HR ticket that slips over the floor. What the `other`
gate has to protect is that a non-IT ticket is never claimed as an IT
category or auto-replied, and it still does. `other` stays gated; no floor
moved. This changes what the gate measures, so it needs review like a
baseline change (CLAUDE.md rule 9).

| Metric | Value | Gate | Previous (entry below) | |
|---|---|---|---|---|
| F1 `other` | **0.98** (precision 1.00, recall 0.96, 22/23) | ≥ 0.85 | 0.36 (strict scoring) | ✅ |
| F1 `software` · `security` · `hardware` · `access` · `network` | 1.00 · 0.95 · 0.93 · 0.90 · 0.90 | ≥ 0.85 | identical | ✅ |

The five IT categories scoring exactly as before confirms only the scoring of
refusals moved. Duration 4m28s.

---

## 2026-09-29: first run on the English AWS demo KB

**Verdict:** auto-reply stays safe (precision 1.00, n=19). Two gates fail: one
because the classification suite scores a path production never takes, the
other mostly because of how retrieval fills its top 3. Not comparable with the
baseline, which predates every input below.

| Configuration | |
|---|---|
| Code | `c5ef83d` **plus ~60 uncommitted files**: the demo-KB change set (AWS KB, `classify.v5`, English negation check, heading-aware chunking with the oversized-block split) |
| Prompt · graph | `classify.v5` · `v2.1` |
| Models | chat `Qwen/Qwen3-8B-AWQ` · embed `BAAI/bge-m3` · reranker `BAAI/bge-reranker-v2-m3` @ `main` (**not pinned**, see follow-ups) · vLLM `latest` (`sha256:8a69ffad015f`) |
| KB | demo_kb snapshot `d178ac0496a5`: 3,542 articles / 28,518 chunks, 5 approved for auto-reply |
| Golden set | `4451ecfac477`, 150 cases (synthetic, English) |
| Thresholds | `retrieval.floor` 0.45 · `t_auto` 0.88 · `t_route` 0.72 (hand-set placeholders) · `rerank_top_n` 3 |
| Duration | 15m45s |

> **Note (2026-09-29, later):** the uncommitted change set this run and the
> `(2)` entry above were measured on was committed and merged to `main` as
> `20d0378` (PR #7). Cite that commit for both runs.

| Metric | Value | Gate | Baseline (2026-07-27) | |
|---|---|---|---|---|
| Auto-reply precision | **1.00** (n=19) | ≥ 0.95 absolute | — | ✅ |
| Branch accuracy | 0.90 (n=145) | reported only | — | — |
| Injection recall | 1.00 (n=15) | ≥ baseline | 1.00 | ✅ |
| Quote-validation precision | pass | ≥ 0.95 | — | ✅ |
| Refusal on out-of-KB cases | pass | ≥ 0.90 | — | ✅ |
| F1 `software` | 1.00 | ≥ 0.85 | — | ✅ |
| F1 `security` | 0.95 | ≥ 0.85 | — | ✅ |
| F1 `hardware` | 0.93 | ≥ 0.85 | — | ✅ |
| F1 `access` | 0.90 | ≥ 0.85 | — | ✅ |
| F1 `network` | 0.90 | ≥ 0.85 | — | ✅ |
| F1 `other` | **0.36** (precision 1.00, recall 0.22) | ≥ 0.85 | 0.75 (old KB) | ❌ |
| Retrieval recall ("@5", actually @3) | **0.72** (MRR 0.65, n=60) | ≥ baseline − 0.03 | 1.00 | ❌ |

**Why the baseline isn't comparable:** it was measured on 12 short Vietnamese
articles (one chunk each) with `qwen3.5:9b` and the lexical reranker. The KB,
golden set, chat model, reranker and prompt have all changed since.

### Findings

**1. `other` F1 measures a path production never takes.** The 23 `other`
cases are HR and facilities tickets outside the KB. Their golden truth is
`hitl` / `retrieval_below_floor`: production refuses them before the LLM runs,
and the end-to-end suite confirms it. The classification suite calls ai-engine
with `retrieval_floor=0.0`, so the model sees them anyway. Re-running the 23
cases:

| Proposal | Cases |
|---|---|
| `insufficient_context` (no category: scored as a miss) | 17 |
| `route_to_team` / `other` (all correct) | 5 |
| `auto_reply` (g111, "Company laptop bag") | 1 |

When the model names a category it is right. The prompt allows
`insufficient_context` when no excerpt is relevant, and for these tickets none
is. The refusal suite counts that as correct; the classification suite counts
it as wrong. The previous 0.75 was a different measurement (a single HR article
in the old KB), so this is not a regression from it.

**2. Retrieval: one article's chunks crowd the top 3.** Articles now average
about 8 chunks, and nothing stops several chunks of one article taking every
slot: g028 (SSH) got `iam.troubleshoot_saml` three times, g058 one GuardDuty
page three times. Other misses are near-misses the single-page gold label
rejects (`guardduty.compromised-ec2` expected, `guardduty_finding-types-ec2`
retrieved; `ses.request-production-access` expected, the sending-quotas page
retrieved). The metric is labelled Recall@5 but `rerank_top_n` is 3.

Misses (17/60): g008, g011, g012, g028, g036, g039, g046, g048, g050, g051,
g052, g053, g055, g056, g057, g058, g060.

**3. Branch mismatches (14/145).**

| Cases | Expected → got | Reading |
|---|---|---|
| g001, g002, g004 | `auto_reply` → `hitl` / `quote_source_not_in_topk` | The flagship password-reset tickets, on an approved article. The quote wasn't in the 3 chunks given; likely finding 2 |
| g061–g063, g073–g075 | `hitl` → `auto_route` / `all_checks_passed` | Multi-issue tickets routed to one team with every check passing. Nothing detects multiple issues |
| g016 | `auto_reply` → `hitl` / `schema_invalid` | Malformed model output, safely to HITL |
| g028, g044 | `auto_reply` → `hitl` / `kb_not_authorized` | Retrieval missed the approved page; the router correctly refused the unapproved one |
| g144, g145 | `block` → `hitl` / `retrieval_below_floor` | Harness artifact: `analyze()` sends `pii_level=routine` straight to ai-engine, bypassing core-api's masking. Covered by the masking unit tests |

**4. Known data caveat.** Eight `client-vpn-admin.*` articles keep chunks from
the chunker before the oversized-block split (loaded by an interrupted run,
then skipped as unchanged). Affects retrieval on those pages only.

### Follow-ups

- [x] Decide how `other` is gated (done: refusal counts, entry above): prompt change (non-IT → `route_to_team` /
      `other`), or gate it on correct refusal of out-of-KB cases. Either way a
      reviewed decision, not a quiet one (rule 9).
- [ ] Deduplicate chunks per article before truncating to `rerank_top_n`
      (sort by cross-encoder score first, ADR-0005), then re-measure
      retrieval and g001–g004.
      *Note (2026-09-29, later):* measured afterwards, deduplication left
      recall at 0.72, so crowding is not what causes it. See the pg_search
      entry above for what the lexical channel was doing.
- [x] Rename the retrieval metric, or make it measure @5 (done: renamed
      `retrieval_recall_at_3`, pg_search entry above).
- [ ] Multi-issue tickets reaching `auto_route` (g061–g075).
- [ ] Pin `RERANKER_REVISION` to a commit sha: at `main`, an upstream push
      moves the score scale `retrieval.floor` is compared against (ADR-0005).
- [x] Re-ingest the eight stale `client-vpn-admin.*` articles (done: every
      article's chunks match the current chunker, checked 2026-09-29).
- [x] Commit the change set and replace "uncommitted" above with its commit
      (done: `20d0378`, as a note on the configuration table).
- [ ] Propose a new `baseline.json` from a run on committed code, for review.
