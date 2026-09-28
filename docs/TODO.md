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

Tests in `services/core-api/apps/tickets/tests/` cover:

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

Investigate whether the fix belongs in the KB content (KB-0010 is thin and semantically distant from the tickets that should match it) or in the classification prompt (`services/ai-engine/src/ai_engine/core/prompts/classify.v3.md`). Prompt changes go through the eval gate like code changes.

### Done when

`other` F1 ≥ 0.85 and the `_known_issue` note is removed from `baseline.json`.

> **Do not** lower the floor, average the F1, or drop the category to make CI green. Per-category F1 exists precisely so a rare category cannot hide behind a healthy mean.

---

## 4. Calibrate `retrieval.floor`, and make the provider/floor pairing knowable

**Priority:** High · **Spec:** §6.3, ADR-0005

### Problem

The cross-encoder is the default: `RERANKER_PROVIDER=vllm` serves `bge-reranker-v2-m3` from vllm-rerank (ADR-0009). Calibration is not done:

- `retrieval.floor = 0.45` is a **cross-encoder** score (🔧, never fitted).
- It was written against FlagEmbedding's sigmoid-normalized `compute_score(normalize=True)`; whether vLLM returns that same scale is unverified.
- Under `lexical` (CI), the floor is compared against a token-overlap ratio. Different question, no error, no test that can see it.

Note the shape of this: it is not "the wrong number", it is "a number from a different measurement compared against this one". Fixing it by nudging `0.45` would be the worst outcome, because it would make the mismatch invisible rather than absent.

There is also a structural blocker. core-api owns `thresholds.yaml` and sends `retrieval_floor` in `AIRunRequest` ([ai_engine.py](../services/core-api/integrations/ai_engine.py)), but `RERANKER_PROVIDER` is read only by ai-engine. **core-api cannot see which provider scored**, so it cannot select a matching floor, and a mismatch cannot currently be detected at all.

### Work

1. Pin `RERANKER_REVISION` to a commit sha in `infra/.env` (it is passed to vllm-rerank). Do this first — with it at `main`, an upstream push moves the distribution out from under whatever you measure.
2. Confirm vllm-rerank's scores are in [0, 1] on the sigmoid scale, then run the pipeline under `vllm` and **look at the score distribution** before choosing anything. The GPU job in `eval-gate.yml` is the natural place.

   ```bash
   RERANKER_PROVIDER=vllm uv run --package evals pytest evals/suites/test_retrieval.py -q
   ```
3. Derive floor and margin from what you observe, not from what keeps CI green.
4. Close the coupling. Options, cheapest first: have ai-engine echo its provider in `AIRunResponse` so core-api can log or reject a mismatch; or move the floor per-provider in `thresholds.yaml` and give core-api the provider setting (accepting that two services then share a value that can disagree).

### vLLM (ADR-0009)

The in-process FlagEmbedding reranker is removed, so there is no local score
to compare against: step 2 above is the check. Both services now embed through vLLM, so the KB chunks, ticket
embeddings and few-shot examples already in pgvector must be re-embedded
through it. Masking's tier-2 NER moved to `CHAT_MODEL` and needs its
detection quality re-checked on real tickets. None of the vLLM path has run
against real hardware yet.

### Done when

`Recall@5 ≥ 0.90` holds under `vllm` with floor and margin derived from observed scores, `RERANKER_REVISION` is a sha, the 🔧 markers are gone from `retrieval` in `thresholds.yaml`, and a provider/floor mismatch is detectable rather than silent.

> Per hard rule 9: do not move the floor to make a suite green. If the numbers disagree, that is the finding.

---

## 5. Wire up an external trace backend

**Priority:** Low · **Spec:** §11.2

### Problem

`trace_id` is minted per request and propagated core-api → Celery → ai-engine, and lands on `audit_log.trace_id`, so a ticket's history is reconstructable from the database alone. What is missing is the LangSmith/Langfuse exporter that would let you jump from a business log line into the full LLM trace (prompt, retrieved chunks, token counts) for that same request.

### Done when

A trace ID from `audit_log` resolves to a complete LLM trace in the chosen backend, with the §11.2 span attributes attached: `ticket_public_id`, `prompt_version`, `graph_version`, `thresholds_version`, `shadow_mode`.

---

## 6. Follow-ups surfaced by the node-class refactor

Three defects found while converting the graph nodes to classes, each
deliberately left out of that refactor so it stays behaviour-preserving.

### 6a. `AIRunRequest.prompt_version` is echoed but never honored

**Priority:** Medium · **Spec:** §12.3

`main.py` returns the caller's `prompt_version` in `AIRunResponse` while the
graph runs whatever `settings.prompt_version` resolves to. The response
therefore asserts a version that did not run, which corrupts both the audit
trail and eval attribution — a metric movement gets blamed on the wrong
prompt.

Actually honoring the field is worse than the bug: it needs per-request node
construction (the graph is built once at import), and it lets a caller pick a
prompt that never passed the eval gate spec §12.3 requires. 

**Done when** `main.py` either returns `settings.prompt_version`, or rejects a
request whose `prompt_version` does not match with a 400.

### 6c. The same query is embedded twice per ticket

**Priority:** Low

`HybridRetrieveNode` and `SelectFewshotsNode` both embed the identical
`subject_masked\nbody_masked` string — two HTTP round-trips where one would
do, on the latency-critical path.

The fix is a `query_embedding` key in `TriageState`, which is a state-shape
change. A caching decorator on the embedder is the **wrong** answer: the graph
is built once at import and has no request scope, so such a cache would be
process-lifetime and grow unboundedly across tickets.

**Done when** one embedding call per ticket is visible in a trace.

### 6d. `embed()` is called while holding a DB connection

**Priority:** Low

In `HybridRetrieveNode`, the embedding round-trip happens inside
`with self._db.connect()`, pinning an `ai_engine_ro` connection for the
15–20s a cold model load can take. Hoisting it out is a small change
but it reorders two I/O operations and their failure sequence, so it wants
its own commit and its own test.

---

## 7. Prefix every table with its owning module

**Priority:** Low · **Blocks:** nothing · **Touches:** the spec-DDL naming convention

### Problem

Browsing the database in a client (Beekeeper, pgAdmin), 20-odd tables sit in
one flat `public` list with no indication of which Django app owns them. Some
already carry a module prefix by accident of naming (`kb_*`, `review_*`,
`fewshot_examples`, `audit_log`, `ticket_embeddings`); the rest do not, so
`incidents`, `ai_runs` and `pii_quarantine` look unrelated to `tickets` even
though the `tickets` app owns all three.

The rule to adopt: **a table's name starts with its module's prefix**, e.g.
everything the authentication module (`apps.accounts`) owns starts with
`auth_`.

### Proposed mapping

Only the tables in **bold** change; the rest already conform.

| Module (app) | Prefix | Current → proposed |
|---|---|---|
| `accounts` | `auth_` | **`accounts_user` → `auth_user`** (Django's own `auth_group` / `auth_permission` then sit alongside it) |
| `tickets` | `ticket_` | `tickets` (root, unchanged) · `ticket_embeddings` · **`incidents` → `ticket_incidents`** · **`ai_runs` → `ticket_ai_runs`** · **`routing_decisions` → `ticket_routing_decisions`** · **`pii_quarantine` → `ticket_pii_quarantine`** · **`pii_access_log` → `ticket_pii_access_log`** |
| `kb` | `kb_` | `kb_articles` · `kb_chunks` · `kb_authority_log` |
| `review` | `review_` | `review_items` · `review_decisions` · **`eval_candidates` → `review_eval_candidates`** |
| `fewshot` | `fewshot_` | `fewshot_examples` |
| `audit` | `audit_` | `audit_log` |
| `itsm_mock` | `itsm_` | **`runbook_executions` → `itsm_runbook_executions`** |

Two things to decide before starting, not during:

- **PII tables:** keep them under `ticket_`, or give PII its own `pii_` module?
  They are the most security-sensitive tables in the schema, and a separate
  prefix makes them easy to spot and to target with grants.
- **Prefixes or Postgres schemas?** Schemas (`auth.user`, `ticket.ai_runs`)
  group tables natively in every client and allow per-schema `GRANT`s, but
  Django's schema support is awkward (`search_path` or quoted `db_table`).
  Prefixes are the low-risk default.

### Work

1. **Write an ADR first.** `CLAUDE.md` and `apps/tickets/models.py` state that
   table names mirror the spec DDL in `requirement.md`, and
   `infra/migrations/sql/` is written against those exact names. This change
   deliberately breaks that alignment, so it needs to be a recorded decision
   with a spec-name → table-name mapping, not a quiet rename.
2. Change `db_table` on each model and generate `AlterModelTable` migrations
   with `makemigrations`. Postgres keeps indexes, CHECKs, triggers and grants
   attached through `ALTER TABLE … RENAME` (they bind by OID), so existing
   databases migrate in place.
3. **Do not edit the historical SQL in `infra/migrations/sql/`.** On a fresh
   database those files run against the old names before the rename migration
   runs. Add a comment to each file noting the later rename instead. Make sure
   the rename migration depends on `dbextras.0002_finalize` so it runs after
   them.
4. Update the raw table names outside the ORM: `evals/calibration/*.py`,
   `evals/suites/*.py`, `apps/metrics/selectors.py`, and any raw SQL in core-api
   services. ai-engine (`core/db/tables.py`) reads only `kb_articles`,
   `kb_chunks` and `fewshot_examples`, which do not change under this mapping.
   If the mapping changes, ai-engine and `0004_grants_and_audit_lockdown.sql`'s
   grant list move with it.
5. Update the table names in `docs/` (architecture, runbooks, glossary) and the
   Layout section of `CLAUDE.md`.

### Done when

- Every table in `public` except Django's own (`django_*`, `auth_group*`,
  `auth_permission`) starts with its owning module's prefix.
- `uv run pytest` passes, and so does a fresh `docker compose up` from an empty
  `db_data` volume. That proves the historical SQL still applies before the
  rename.
- `audit_log` still rejects UPDATE/DELETE and `ai_engine_ro` can still read
  exactly its three tables after the rename. Both guardrails must survive it.

---

## 8. Housekeeping

- **Golden set is synthetic.** Per spec §12.4, promote real cases into `evals/golden/tickets.jsonl` over time from the three free label sources already being captured: human overrides, technician reroutes, and reopens after auto-reply. `eval_candidates` rows are accumulating for exactly this — they just need a periodic review-and-promote pass.

- **The OpenAI cost rate is a placeholder.** `OPENAI_COST_PER_1K_TOKENS` in
  `models.py` is illustrative. Replace it with the real rate card for
  `CLOUD_MODEL` before `cost_per_ticket` dashboards are trusted — the number
  is currently plausible-looking and wrong.
