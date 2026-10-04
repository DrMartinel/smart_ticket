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

1. Reveal endpoint in `apps/tickets/views.py`, e.g. `POST /api/tickets/{public_id}/quarantine/{ref}/reveal`, with a mandatory non-empty `reason` in the body.
2. RBAC: `security` role, and/or a technician who has claimed the related `pii_verify` review item. Gate the endpoint with `@require_role(...)` from `apps/accounts/permissions.py`; `auto_reply_allowed` makes its manager-only check in `KbArticle.set_auto_reply_allowed` (`apps/kb/models.py`), which no router enforces yet.
3. Write the `PiiAccessLog` row in the **same transaction** as the decrypt — a successful read must be structurally incapable of happening without its log line.
4. Reject reads past `expires_at`.
5. Consider an audit event as well (`AuditLog.objects.record()` in `apps/audit/models.py`) for the business-level trail.

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

## 3. ~~Decide how the `other` category is gated~~ (decided 2026-09-29)

On an out-of-KB case, the classification suite now counts `insufficient_context` as correct, matching `test_refusal.py` and spec §12.2; an IT category or `auto_reply` on such a ticket still fails. `other` F1 is **0.98** under that rule. The reasoning and the alternative that was rejected (a prompt change routing non-IT tickets to `other`) are in [`evals/HISTORY.md`](../evals/HISTORY.md), entry "2026-09-29 (2)".

Left to do: the change to what the gate measures needs review by someone other than its author, like a baseline change, and the `_known_issue` note in `baseline.json` goes when the next baseline is proposed.

---

## 4. Calibrate `retrieval.floor` on Jev's scale

**Priority:** High · **Spec:** §6.3, ADR-0005, ADR-0015

### Problem

Since 2026-10-03 Jev is the reranker on every run ([ADR-0015](adr/0015-jev-reranks-the-shortlist.md), written 2026-10-04): the cross-encoder (`SHORTLIST_PROVIDER=vllm`, bge-reranker-v2-m3 on vllm-rerank) scores the fused candidates plus link-expanded chunks, and Jev re-scores its top 15. `retrieval.floor` is on **Jev's** scale and is compared only with Jev's top-1; the cross-encoder's score only orders the pool and picks the shortlist, so it no longer needs a floor of its own. Calibration is not done:

- `retrieval.floor = 0.30` (🔧) is the middle of the probe's 0.12-0.48 gap, chosen from **golden-set** data (evals/HISTORY.md 2026-10-02 (4)-(5)).
- The trust coefficients, `t_auto` and `t_route` were hand-set for the cross-encoder's `rerank_top1` and margin; Jev's top-1 sits on a different distribution.
- The cross-encoder's scale still matters for which 15 chunks Jev sees: pin `RERANKER_REVISION` so an upstream commit can't move it.

Note the shape of this: it is not "the wrong number", it is "a number from a different measurement compared against this one". Fixing it by nudging `0.30` would be the worst outcome, because it would make the mismatch invisible rather than absent.

### Work

1. Pin `RERANKER_REVISION` to a commit sha in `.env.example` (it is passed to vllm-rerank).
2. Choose the Jev floor and margin on shadow pairs, not the golden set: look at Jev's top-1 distribution for tickets humans resolved from the KB vs. not.
3. Refit the trust coefficients (item 2) on Jev-scale signals before P3.

### vLLM (ADR-0009)

The in-process FlagEmbedding reranker is removed, so there is no local score
to compare against. Every embedding now comes from vLLM through ai-engine (ADR-0012), so the KB chunks, ticket
embeddings and few-shot examples already in pgvector must be re-embedded
through it. Masking's tier-2 NER runs in ai-engine on `CHAT_MODEL` and needs its
detection quality re-checked on real tickets. None of the vLLM path has run
against real hardware yet.

### Done when

`Recall@3 ≥ 0.90` holds under `vllm` + Jev with floor and margin derived from shadow pairs on Jev's scale, `RERANKER_REVISION` is a sha, and the 🔧 markers are gone from `retrieval` in `thresholds.yaml`.

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

### 6d. ~~`embed()` is called while holding a DB connection~~ Done 2026-10-03

Every read now borrows a pooled connection for one statement (`db.all` /
`db.first`), so nothing can hold one across a model call. Pinned by
`test_retrieve.py::test_no_db_connection_is_held_while_embedding`.

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
   `evals/suites/*.py`, `apps/metrics/utils.py`, and any raw SQL in core-api
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

---

## 9. Retrieval recall on the AWS demo KB (failing CI gate)

**Priority:** High · **Spec:** §12.2 · **ADR:** 0005

### Problem

Retrieval recall @3 is **0.767** (the 2026-10-01 baseline in [`evals/HISTORY.md`](../evals/HISTORY.md); first reached by pg_search, entry 2026-09-29 (3) in [`evals/HISTORY-archive.md`](../evals/HISTORY-archive.md)), up from 0.72 once the lexical channel started working (ADR-0013: the old BM25 matched nothing, silently). Chunk crowding was the earlier explanation; deduplicating chunks per article left recall at 0.72, so it isn't the cause.

Of the 14 remaining misses, 9 are GuardDuty and SES tickets (g048, g050–g053, g055, g056, g058, g060) where the ticket describes symptoms and the KB page uses finding or feature names. Neither BM25 nor the vector channel bridges that vocabulary gap. Some other misses are near-misses a single-page gold label rejects.

### Work

- Investigate the vocabulary-mismatch misses case by case: why a short remediation page (`guardduty.compromised-ec2`) loses to a long reference page (`guardduty_finding-types-ec2`).
- Candidate expansion through article associations, and LLM re-ordering above the floor: proposed in [ADR-0014](adr/0014-candidate-expansion-and-llm-reorder.md). Probes on multi-chunk retrieval as in production (2026-10-01 (2) in `evals/HISTORY-archive.md`): KB links 0.767 → 0.800, plus Qwen3-8B re-ordering with both-orders agreement → 0.850, nothing lost, refusal unchanged (0.850 → 0.883 with one chunk per article, since reverted). Article-first retrieval and zero-shot Laya make recall worse. Open before acceptance: a full eval run, the injection tickets, and an association source for KBs without links.
- Review whether some tickets have more than one correct page. Choose acceptable pages without looking at model output, and have someone other than the author review them, so this doesn't turn into relabelling until the gate passes (rule 9).
- Pin `RERANKER_REVISION` to a commit sha: at `main`, an upstream push moves the score scale `retrieval.floor` is compared against.
- Do not tune `retrieval.keyword_agreement_k`, the tokenizer, the candidate limits or RRF k against the golden set; that is shadow-calibration work (item 2).
- Re-measure, and record the run in `evals/HISTORY.md`.

### Done when

Retrieval recall meets the gate against a reviewed baseline measured on this KB.

---

## 10. Ask the requester when a ticket is ambiguous (clarification branch)

**Status (2026-10-04):** the decision path is implemented, [ADR-0016](adr/0016-clarify-branch.md) (Proposed): `ClarificationProposal` and `classify.v6`, the validator's `clarify_options_in_topk`, `Branch.CLARIFY` in `router.py` (after every hard gate, never for `security`), and execution as a review item in the `clarification` queue. g151-g156 expect `clarify`. **Left:** the requester side (steps 4 and 6 below, the round cap of step 3), decided in a later ADR before shadow mode ends.

**Priority:** Medium, after item 4 (it does not fix the failing auto-reply gate) · **Spec:** §5, §8 · **ADR:** [0016](adr/0016-clarify-branch.md)

### Problem

Some tickets have a plausible KB answer but leave out the detail that says whether it applies. The 2026-10-02 (5) full run ([`evals/HISTORY.md`](../evals/HISTORY.md)) had two:

- **g148**, "I need help resetting my portal password": Jev ranks `identity-center.resetpassword-accessportal` top-1 at 0.92 and the run auto-replies 2 times in 3. The ticket never says *which* portal. The labeled g001-g005 all say "AWS access portal", "access portal" or "Identity Center".
- **g150**, "connection error when connecting to the internal server at 10.0.4.22": auto-replies 3 times in 3 with `ec2.TroubleshootingInstancesConnecting`, though nothing says the server is an EC2 instance.

The router can only guess (`auto_reply`) or hand the ticket off (`auto_route`, `hitl`, `escalate`, `block`). A human then asks the question by hand, or the requester gets an answer to a question they didn't ask.

### Work

1. **Write the ADR first.** This lets the system send the requester something other than a human reply or an approved KB answer, so it widens what the LLM can cause without a human. The ADR has to say why that is safe.
2. **The LLM proposes, the router decides.** ai-engine returns a `proposed_clarification` (the question, and which KB pages it would separate). `router.py` decides whether to ask, from deterministic rules with thresholds passed in. For example: ask only when the top page has `auto_reply_allowed` and trust falls between `t_route` and `t_auto`. Never ask on `block`, high-risk or PII-critical tickets, and never on a `RunbookProposal` (ADR-0006).
3. A new `Branch` value (e.g. `clarify`) and its `ReasonCode`s. Every limit (rounds, wait time) goes in `thresholds.yaml`.
4. **Failure paths go to HITL, each with its own `ReasonCode`:** no reply within the wait time, a reply that is still ambiguous, the round cap reached (one question, then a human), and an LLM question that is empty or malformed.
5. Wire schema in both services in the same PR (`infrastructure/dtos.py`, ai-engine `schemas.py`), new fields defaulted, `make types` for web.
6. Re-run the pipeline on the requester's reply: the original ticket plus the answer, masked again, since the reply can contain PII.
7. Golden cases for ambiguous tickets with `expected_branch: clarify`, chosen and reviewed by someone other than the author (rule 9). Don't relabel g148/g150 to make the precision gate pass.

**Cheaper first step, worth measuring before any of the above:** the auto-reply states its assumption ("If you mean the AWS access portal, …"). This is only a prompt change, so it goes through the eval gate with a version bump.

### Done when

The ADR is accepted. Ambiguous tickets reach `clarify` in the evals without lowering auto-reply precision. Every clarification failure path has a test that ends in HITL with its `ReasonCode`. And shadow mode records `clarify` decisions so they can be compared with what technicians actually asked.

---

## 11. Accept or reject ADR-0017 (Jev chooses the category)

**Status (2026-10-04):** built, [ADR-0017](adr/0017-jev-classifies-the-category.md) (Proposed): `ClassifyCategoryNode` asks Jev `category.v1`, `TrustSignals.classification` carries the answer, and `router.py` routes clarify and auto-route on Jev's choice, sending it to a human as `category_low_confidence` below `classification.min_confidence` (0.65 🔧). The LLM's `proposed_category` is log-only.

**Priority:** High · **Spec:** §8, §12.2 · **ADR:** 0017

### Work

- A full eval run with it built, the end-to-end suite included, recorded in `evals/HISTORY.md`. The classification suite now scores Jev's choice at the real floor.
- Re-measure on tickets `category.v1` was not written against (a held-out set or shadow data); the probe's 80/83 was measured on the set the question was tuned on.
- Choose `classification.min_confidence` on shadow data, not the probe's 83 tickets.
- Re-decide `category_consistent`: it is hard-coded true for every non-auto-reply proposal, so its route gate and trust feature have never compared anything.

### Done when

The ADR is accepted or superseded on a full run and a held-out measurement.
