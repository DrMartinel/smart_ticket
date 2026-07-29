# TODO

Outstanding work, ordered by priority. Each item states why it matters and what "done" looks like, so it can be picked up without re-deriving the context.

Status of what already works is in [`status.md`](status.md); these are its open gaps made actionable. Update both together.

---

## 1. Implement the PII quarantine read path + access log

**Priority:** High · **Blocks:** the `pii_verify` review queue · **Spec:** §3.1

### Problem

The **write** half of PII quarantine is complete — masking encrypts raw values with AES-GCM into `pii_quarantine` (72 h TTL) on submit. The **read** half does not exist:

- `crypto.decrypt()` is defined but never called from anywhere.
- The `PiiAccessLog` model exists but nothing ever writes a row.
- There is no endpoint to reveal a quarantined value.

Spec §3.1 is unambiguous: *"Mỗi lần đọc PII raw là một dòng log. Không có ngoại lệ."* — every raw-PII read writes an access-log row with a mandatory non-empty `reason`.

This currently **fails safe** (nobody can read raw PII at all, which is stricter than required), so it is not urgent in the security sense. But the `pii_verify` queue exists and routes tickets to humans who will eventually need to see the masked values to do their job — and the moment someone adds a `decrypt()` call to serve that need, the logging requirement must already be in place. The risk is that it gets bolted on later under pressure, without the log.

### Work

1. Reveal endpoint in `apps/tickets/api.py`, e.g. `POST /api/tickets/{public_id}/quarantine/{ref}/reveal`, with a mandatory non-empty `reason` in the body.
2. RBAC: `security` role, and/or a technician who has claimed the related `pii_verify` review item. Follow the manager-only pattern already used for `auto_reply_allowed` in `apps/kb/api.py`.
3. Write the `PiiAccessLog` row in the **same transaction** as the decrypt — a successful read must be structurally incapable of happening without its log line.
4. Reject reads past `expires_at`.
5. Consider an `audit()` event as well (`apps/audit/services.py`) for the business-level trail.

### Done when

Tests in `services/core-api/tests/` cover:

- successful reveal writes exactly one `pii_access_log` row carrying actor and reason;
- empty or missing `reason` → rejected;
- wrong role → rejected;
- expired entry → rejected;
- no code path returns plaintext without a corresponding log row.

---

## 2. Calibrate the trust score and choose real thresholds

**Priority:** High · **Blocks:** P3 and P4 rollout · **Spec:** §7.1, §14

### Problem

`trust_model_v0.json` ships hand-set logistic-regression coefficients, documented in-file as an assumption. They are not fitted to anything. Consequently `t_auto = 0.88` and `t_route = 0.72` in `thresholds.yaml` are placeholders wearing the costume of tuned values.

This is the expected P1 state, not a defect — but it is the single thing standing between here and enabling any automation.

### Work

Shadow mode is already collecting the needed data. Once there are **≥500** `(signals, human verdict)` pairs:

```bash
uv run python evals/calibration/fit_trust_score.py
uv run python evals/calibration/choose_thresholds.py
```

Pick thresholds by **precision on a holdout set**, not accuracy: `t_auto` = smallest threshold where auto-reply precision ≥ 0.95; `t_route` = smallest where route precision ≥ 0.85. Commit the refitted model and the new `thresholds.yaml` with `calibration_source` updated to name the run.

### Decide during calibration: should route proposals share auto-reply's curve?

`FEATURES` includes `quote_match_ratio` and `quote_source_in_topk`, which only
mean anything for an `AutoReplyProposal`. A route or runbook proposal has no
verbatim quote, so those features are always 0 for it and it can never earn
their weight — meaning route proposals are scored on a curve whose upper range
is effectively unreachable for them.

This is currently handled by `scored_features()` skipping the two features when
`quote_applicable=False`. That is an **explainability** fix only: both are linear
terms, so a 0.0 value contributes 0.0 either way and no score or routing decision
changes. It just keeps them out of `contributions` so the UI can show "not
applicable" instead of a red ✗.

The real question is whether route proposals want their own feature set and their
own fitted curve. Decide it here, with data, rather than by intuition — and note
that `t_route < t_auto` already compensates for some of the gap by design.

### Done when

Auto-reply precision ≥ 0.95 on holdout, and `thresholds.yaml` no longer carries 🔧 markers on `t_auto` / `t_route`.

> Do not enable P3/P4 before this. Thresholds chosen by intuition are exactly what shadow mode exists to replace.

---

## 3. Fix the `other` category F1 (failing CI gate)

**Priority:** Medium · **Spec:** §12.2

### Problem

`evals/suites/test_classification.py::test_per_category_f1_meets_threshold` fails: `other` scores **F1 0.75** against the 0.85 absolute floor. Precision is 1.00, recall 0.60 — the model under-assigns the category rather than over-assigning it.

The category maps to a single KB article (KB-0010, long-term leave requests — an HR matter that happens to arrive through the IT ticket system), and classification on it is inconsistent.

This is recorded in `evals/baselines/baseline.json` as a known issue rather than smoothed into the baseline.

### Work

Investigate whether the fix belongs in the KB content (KB-0010 is thin and semantically distant from the tickets that should match it) or in the classification prompt (`services/ai-engine/src/ai_engine/llm/prompts/classify.v3.md`). Prompt changes go through the eval gate like code changes.

### Done when

`other` F1 ≥ 0.85 and the `_known_issue` note is removed from `baseline.json`.

> **Do not** lower the floor, average the F1, or drop the category to make CI green. Per-category F1 exists precisely so a rare category cannot hide behind a healthy mean.

---

## 4. Switch the reranker to the real cross-encoder

**Priority:** Medium · **Spec:** §6.3, ADR-0005

### Problem

`RERANKER_PROVIDER=lexical` is the default — a deterministic lexical-overlap scorer that needs no model download and no GPU, which keeps CI and offline development fast. It is not what the spec's retrieval quality assumes.

`retrieval.floor = 0.45` is specified as a **cross-encoder** score. The lexical scorer produces a different score distribution, so the floor and margin are not transferable between the two.

### Work

```bash
uv sync --package ai-engine --extra cross-encoder
# then set RERANKER_PROVIDER=cross_encoder
```

Then **re-tune `retrieval.floor` and `retrieval.margin` against the new distribution** and re-run `evals/suites/test_retrieval.py`. Treat lexical and cross-encoder as two separate calibrations, never interchangeable.

### Done when

Recall@5 ≥ 0.90 holds under `cross_encoder`, with floor/margin values derived from cross-encoder scores and `thresholds.yaml` noting which provider they were calibrated against.

---

## 5. Wire up an external trace backend

**Priority:** Low · **Spec:** §11.2

### Problem

`trace_id` is minted per request and propagated core-api → Celery → ai-engine, and lands on `audit_log.trace_id`, so a ticket's history is reconstructable from the database alone. What is missing is the LangSmith/Langfuse exporter that would let you jump from a business log line into the full LLM trace (prompt, retrieved chunks, token counts) for that same request.

### Done when

A trace ID from `audit_log` resolves to a complete LLM trace in the chosen backend, with the §11.2 span attributes attached: `ticket_public_id`, `prompt_version`, `graph_version`, `thresholds_version`, `shadow_mode`.

---

## 6. Housekeeping

- **`.claude/scheduled_tasks.lock` is tracked in git** and churns on every session. Untrack it:
  ```bash
  git rm --cached .claude/scheduled_tasks.lock && echo '.claude/scheduled_tasks.lock' >> .gitignore
  ```
- **Golden set is synthetic.** Per spec §12.4, promote real cases into `evals/golden/tickets.jsonl` over time from the three free label sources already being captured: human overrides, technician reroutes, and reopens after auto-reply. `eval_candidates` rows are accumulating for exactly this — they just need a periodic review-and-promote pass.
