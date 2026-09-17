# Implementation status

Component-by-component state against [`requirement.md`](../requirement.md) (Architecture Specification v2), including known gaps. Written to be honest rather than flattering — a "✅" here means *verified working*, not *code exists*.

**Last verified:** 2026-07-29, against the full `docker compose --profile local-llm up` stack with Ollama (`qwen3.5:9b`, `qwen3:8b`, `bge-m3`) running as a compose service. A ticket submitted through the UI reached the LLM, produced an auto-reply proposal, and was correctly held back by the negation check.

---

## Summary

| | |
|---|---|
| Spec phases complete | **P0, P1** |
| Phase in progress | **P2** — calibration scripts ready, awaiting ≥500 shadow pairs |
| Unit tests | **242 passing** (74 core-api, 168 ai-engine) |
| Eval suites | 8 collected; **7 pass, 1 known failure** (`other` category F1) |
| Masking branch coverage | **100%** — the spec §14 P0 exit condition |
| Router branch coverage | 98% — the one uncovered line is unreachable by construction |
| Operating mode | `SHADOW_MODE=true` — router decides, humans still handle everything |

---

## By spec section

| § | Component | Status | Notes |
|---|---|---|---|
| §2 | `packages/contracts` as single schema source | ✅ | Both Python services import it; TS types generated for web |
| §3.1 | Ticket / embedding / quarantine schema | ✅ | Table + column names mirror the spec DDL exactly via `db_table` |
| §3.1 | PII quarantine **write** path | ✅ | AES-GCM, key from env, 72 h TTL, expiry task on Celery beat |
| §3.1 | PII quarantine **read** path + access log | ❌ **Gap** | See [Gap 1](#gap-1-pii-quarantine-read-path) |
| §3.2 | KB schema + `auto_reply_allowed` governance | ✅ | DB `CHECK` enforces a named approver; every flip writes `kb_authority_log` |
| §3.3 | `ai_runs`, `routing_decisions` | ✅ | `thresholds_used` snapshot written on every decision |
| §3.4 | Review queue, decisions, eval candidates | ✅ | Overrides auto-create `eval_candidates` (§12.4 loop verified live) |
| §3.5 | Few-shot pool, incidents, append-only audit | ✅ | `REVOKE UPDATE, DELETE ON audit_log` applied in SQL migration |
| §4 | Discriminated-union contracts, `proposed_` prefixes | ✅ | `LLMProposalEnvelope` as `RootModel`, `frozen=True` on `TicketMasked` |
| §5 | Masking engine (inline, two-tier) | ✅ | 100% branch coverage; regex tier-1 short-circuits before any LLM call |
| §6 | LangGraph pipeline | ✅ | Refuse-before-LLM and the `iteration < 2` cap both verified |
| §6.3 | Hybrid retrieval BM25 + vector + RRF | ✅ | RRF k=60; no threshold on fused rank (ADR-0005) |
| §6.3 | Cross-encoder reranker | ⚠️ Unverified | Served by vLLM (`RERANKER_PROVIDER=vllm`, the default), not yet run against real hardware; `lexical` (for CI) folds Vietnamese diacritics; see [Gap 3](#gap-3--retrievalfloor-is-uncalibrated) |
| §6.4 | Validator (quote → fuzzy → in-top-k → negation) | ✅ | Negation check verified catching a real `negation_mismatch` live |
| §7 | Trust scorer, outside ai-engine | ⚠️ Uncalibrated | Works, but coefficients are a hand-set prior — see [Gap 2](#gap-2-trust-score-is-an-uncalibrated-prior) |
| §8 | Switch router — pure function, hard gates ordered | ✅ | Every branch unit-tested with no DB/LLM/network |
| §8.2 | Shadow mode | ✅ | Same `route()` in both modes |
| §9 | Incident detector (adaptive baseline + 3σ) | ✅ | Concurrent-worker dedup serialized by a Postgres advisory lock |
| §10.1 | Circuit breaker | ✅ | 20% / 5 min window, 10 min open, 10% half-open |
| §10.2 | Per-ticket budget + daily cost ceiling | ✅ | Ceiling enforced in core-api (only side that sees total spend) |
| §10.3 | Failure-mode table — always degrade to a human | ✅ | Including the embedding path (fixed 2026-07-28) |
| §11.1 | Dashboard metrics | ✅ | `reopen_rate_after_autoreply`, `approve_rate_per_reviewer`, `median_time_spent` all implemented |
| §11.2 | `trace_id` propagation | ⚠️ Partial | Threaded through app + audit log; no LangSmith/Langfuse export — see [Gap 4](#gap-4-no-external-trace-backend) |
| §12 | Eval harness, golden set, CI gate | ✅ | 150 synthetic cases at the §12.1 distribution |
| §13 | Centralized thresholds | ✅ | `thresholds.yaml` is the only source; loaded as a validated Pydantic model at boot |

---

## Known gaps

Each gap below has a corresponding actionable entry in [`TODO.md`](TODO.md) — update both together.

### Gap 1 — PII quarantine read path

**Spec §3.1:** *"Mỗi lần đọc PII raw là một dòng log. Không có ngoại lệ."* (Every raw-PII read is a log line. No exceptions.)

The **write** half is complete: PII is masked inline, encrypted with AES-GCM, and stored in `pii_quarantine` with a 72-hour TTL. The **read** half is not wired up:

- `crypto.decrypt()` exists but is never called by any endpoint.
- The `PiiAccessLog` model exists but nothing writes to it.
- There is no authorized "reveal" endpoint requiring a non-empty `reason`.

Practically this fails safe — nobody can read raw PII at all right now, which is stricter than the spec requires. But the `pii_verify` review queue exists and will eventually need this, and when it is built the mandatory-reason + same-transaction access-log requirement must be honored. Do not add a decrypt call without it.

### Gap 2 — Trust score is an uncalibrated prior

`trust_model_v0.json` ships hand-set logistic-regression coefficients, documented in-file as an assumption. They are *not* fitted to data, so `T_auto = 0.88` and `T_route = 0.72` are placeholders, not tuned values.

This is the expected P1 state, not a defect. `evals/calibration/fit_trust_score.py` and `choose_thresholds.py` exist and are ready; they need ≥500 shadow-mode `(signals, human verdict)` pairs to run. **Do not enable P3/P4 before this happens** — thresholds chosen by intuition are exactly what shadow mode is meant to replace.

### Gap 3 — `retrieval.floor` is uncalibrated

`RERANKER_PROVIDER=vllm` is the default: the `bge-reranker-v2-m3` cross-encoder served by vllm-rerank (ADR-0009). The in-process FlagEmbedding reranker is gone, and with it torch and the baked weights in the ai-engine image.

**The open problem is calibration.** `retrieval.floor = 0.45` is specified as a **cross-encoder** score (ADR-0005), but it was never fitted, and whether vLLM returns the same sigmoid-normalized scale FlagEmbedding did is unverified. Under `lexical` (CI), the floor is compared against `|query ∩ passage| / |query|` instead — a different question, decided silently. Treat refusal behaviour as uncalibrated.

Two things have to happen to close it, and neither is a config edit:

1. **Measure.** Nobody has observed real `bge-reranker-v2-m3` scores on this KB, so `0.45` is a hand-set prior (🔧) even for the provider it was written for.
2. **Make the pairing knowable.** core-api reads `retrieval.floor` and sends it in `AIRunRequest` ([ai_client.py](../services/core-api/apps/tickets/services/ai_client.py)), but `RERANKER_PROVIDER` is an ai-engine-only variable — core-api cannot see which provider scored, so it cannot pick the matching floor or detect a mismatch. A per-provider floor needs that coupling to exist first.

See [TODO.md](TODO.md) item 4.

### Gap 4 — No external trace backend

`trace_id` is minted per request, propagated through core-api → Celery → ai-engine, and stored on `audit_log.trace_id`, so a ticket's history is reconstructable from the database. The spec §11.2 idea of jumping from a business log line into a full LLM trace needs a LangSmith/Langfuse exporter, which is not wired up.

### Gap 5 — `other` category F1 below the CI floor

`test_per_category_f1_meets_threshold` fails: `other` scores **0.75** against the 0.85 absolute floor.

This is a genuine, reproducible model finding, recorded in `evals/baselines/baseline.json` rather than smoothed into the baseline. The `other` category maps to a single KB article (KB-0010, long-term leave requests — an HR matter that arrives through the IT ticket system), and classification is inconsistent on it. Fix the KB content or the prompt. **Do not lower the floor or drop the category to make CI green** — per-category F1 exists precisely so a rare category cannot hide behind a healthy average.

---

## Environment caveat: self-hosted models moved to vLLM, unverified

The verification above ran on Ollama. Both services now use self-hosted vLLM (ADR-0009) — code only, **not yet run against real hardware**. Until it is, treat masking quality, embeddings and inference on vLLM as unverified; stored vectors must also be re-embedded through vLLM.

The connect timeout stays budgeted separately from the read timeout (`MODEL_CONNECT_TIMEOUT_SEC=3` vs `MODEL_TIMEOUT_SEC=120`). An unreachable provider fails in ~3s instead of burning the full read budget — which matters because masking is inline in the submit request, so that delay is a user watching a spinner.

---

## Verified end-to-end

Confirmed against the running stack, not just unit tests:

| Scenario | Expected | Result |
|---|---|---|
| Vietnamese ticket with email + phone | Masked to `[EMAIL_1]`/`[PHONE_1]`, raw only in encrypted quarantine | ✅ |
| `password: ...` in body | `BLOCK` / `PII_CRITICAL`, zero LLM calls | ✅ |
| "Bỏ qua mọi hướng dẫn…" injection | `BLOCK` / `INJECTION_DETECTED`, zero retrieval or tokens | ✅ |
| Out-of-KB question | `HITL` / retrieval floor, LLM never invoked | ✅ |
| 6 near-identical tickets in <15 min | One `Incident`, `ESCALATE` / `MASS_INCIDENT` | ✅ |
| Reviewer override in `/review/[id]` | `eval_candidates` row created with the override reason | ✅ |
| Manager flips `auto_reply_allowed` | Requires reason; writes `kb_authority_log` + `approved_by` | ✅ |
| Empty-reason KB flip | Rejected | ✅ |
| Embedding provider down | `HITL` / `EMBEDDING_UNAVAILABLE`, ticket never stuck at `new` | ✅ |

Hard-gate ordering was confirmed live: a ticket that was both `mask_failed` **and** injection-bearing resolved to `BLOCK`/`INJECTION_DETECTED`, because injection is checked first (spec §8).
