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
- [ ] Rename the retrieval metric, or make it measure @5.
- [ ] Multi-issue tickets reaching `auto_route` (g061–g075).
- [ ] Pin `RERANKER_REVISION` to a commit sha: at `main`, an upstream push
      moves the score scale `retrieval.floor` is compared against (ADR-0005).
- [ ] Re-ingest the eight stale `client-vpn-admin.*` articles.
- [ ] Commit the change set and replace "uncommitted" above with its commit.
- [ ] Propose a new `baseline.json` from a run on committed code, for review.
