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
| Eval suites | 15 tests; **14 pass, 1 fails** (retrieval recall) on the 2026-10-01 baseline full run; see [`evals/HISTORY.md`](../evals/HISTORY.md) |
| Masking branch coverage | **100%** — the spec §14 P0 exit condition |
| Router branch coverage | 98% — the one uncovered line is unreachable by construction |
| Operating mode | `SHADOW_MODE=true` — router decides, humans still handle everything |

---

## By spec section

| § | Component | Status | Notes |
|---|---|---|---|
| §2 | Schema contracts | ⚠️ Changed | No shared package (ADR-0010): each schema lives in the module that uses it; TS types generated from core-api. Cross-service integration tests not written yet, so wire drift is unguarded |
| §3.1 | Ticket / embedding / quarantine schema | ✅ | Table + column names mirror the spec DDL exactly via `db_table`; keys are UUIDs, not the spec's `BIGSERIAL` (ADR-0011) |
| §3.1 | PII quarantine **write** path | ✅ | AES-GCM, key from env, 72 h TTL, expiry task on Celery beat |
| §3.1 | PII quarantine **read** path + access log | ❌ **Gap** | See [Gap 1](#gap-1-pii-quarantine-read-path) |
| §3.2 | KB schema + `auto_reply_allowed` governance | ✅ | DB `CHECK` enforces a named approver; every flip writes `kb_authority_log` |
| §3.3 | `ai_runs`, `routing_decisions` | ✅ | `thresholds_used` snapshot written on every decision |
| §3.4 | Review queue, decisions, eval candidates | ✅ | Overrides auto-create `eval_candidates` (§12.4 loop verified live) |
| §3.5 | Few-shot pool, incidents, append-only audit | ✅ | `REVOKE UPDATE, DELETE ON audit_log` applied in SQL migration |
| §4 | Discriminated-union contracts, `proposed_` prefixes | ✅ | `LLMProposalEnvelope` as `RootModel`, `frozen=True` on `TicketMasked` |
| §5 | Masking engine (inline, two-tier) | ✅ | 100% branch coverage; regex tier-1 short-circuits before any LLM call |
| §6 | LangGraph pipeline | ✅ | Refuse-before-LLM verified; graph is acyclic (no LLM retry) |
| §6.3 | Hybrid retrieval BM25 + vector + RRF | ✅ | BM25 is pg_search (ADR-0013), departing from the spec's `ts_rank_cd`, which had no IDF and matched nothing on the English KB. RRF k=60; no threshold on fused rank or on BM25 scores (ADR-0005) |
| §6.3 | Cross-encoder shortlister | ⚠️ Unverified | Served by vLLM (`SHORTLIST_PROVIDER=vllm`, the default), not yet run against real hardware; `lexical` (for CI) folds Vietnamese diacritics; picks Jev's shortlist, Jev is the reranker; see [Gap 3](#gap-3--retrievalfloor-is-uncalibrated) |
| §6.4 | Validator (quote → fuzzy → in-top-k → negation) | ✅ | Negation check verified catching a real `negation_mismatch` live |
| §7 | Trust scorer, outside ai-engine | ⚠️ Uncalibrated | Works, but coefficients are a hand-set prior — see [Gap 2](#gap-2-trust-score-is-an-uncalibrated-prior) |
| §8 | Switch router — pure function, hard gates ordered | ✅ | Every branch unit-tested with no DB/LLM/network |
| §8.2 | Shadow mode | ✅ | Same `route()` in both modes |
| §9 | Incident detector (adaptive baseline + 3σ) | ✅ | Concurrent-worker dedup serialized by a Postgres advisory lock |
| §10.1 | Circuit breaker | ❌ Removed | Deliberately dropped to simplify; every LLM failure is `all_llm_down` → HITL |
| §10.2 | Per-ticket budget + daily cost ceiling | ⚠️ Partial | Per-ticket budget removed; daily ceiling still enforced in core-api |
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

Every run shortlists, then reranks (ADR-0015): the `bge-reranker-v2-m3` cross-encoder on vllm-rerank (`SHORTLIST_PROVIDER=vllm`; `lexical` in CI) shortlists the candidates plus link-expanded chunks, and Jev, the reranker, scores its top 15. `retrieval.floor = 0.30` is on Jev's scale (🔧): chosen from golden-set data, not fitted. The trust coefficients were hand-set for the cross-encoder's scores, not Jev's. Treat refusal and trust behaviour as uncalibrated.

Since ADR-0017 (Proposed, 2026-10-04) Jev also chooses the ticket's category, and auto-route and clarify act on it below `classification.min_confidence` = 0.65 (🔧, from one probe on the golden set) only via a human. Built and unit-tested; no full eval run yet ([TODO.md](TODO.md) item 11).

See [TODO.md](TODO.md) item 4.

### Gap 4 — No external trace backend

`trace_id` is minted per request, propagated through core-api → Celery → ai-engine, and stored on `audit_log.trace_id`, so a ticket's history is reconstructable from the database. The spec §11.2 idea of jumping from a business log line into a full LLM trace needs a LangSmith/Langfuse exporter, which is not wired up.

### Gap 5 — Retrieval recall below the CI floor

Measured on the full golden set in the 2026-10-01 baseline run ([`evals/HISTORY.md`](../evals/HISTORY.md)); earlier runs, with their configuration and per-case findings, are in [`evals/HISTORY-archive.md`](../evals/HISTORY-archive.md).

- **`other` F1** failed at 0.36 under strict scoring, which counted a refusal on an out-of-KB ticket as a miss, the opposite of the refusal suite. Rescored so that refusal counts (a reviewed decision, [`TODO.md`](TODO.md) item 3), it is **0.95** on the baseline.
- **Retrieval recall@3 0.767** against `baseline.json`'s 1.00, which was measured on 12 one-chunk articles and isn't comparable. Mostly tickets that describe a symptom while the answering page is named after the cause or fix; chunk crowding explains one case. Proposed fix: [ADR-0014](adr/0014-candidate-expansion-and-llm-reorder.md) ([`TODO.md`](TODO.md) item 9).

Auto-reply precision on the same run is 1.00 (n=19). **Do not lower a floor or drop a category to make CI green** — per-category F1 exists precisely so a rare category cannot hide behind a healthy average.

---

## Environment caveat: self-hosted models moved to vLLM, unverified

The verification above ran on Ollama. The system now uses self-hosted vLLM (ADR-0009), reached only through ai-engine: core-api's PII NER and embeddings go through ai-engine's `/v1/pii/detect` and `/v1/embed` (ADR-0012). All of it is code only, **not yet run against real hardware**. Until it is, treat masking quality, embeddings and inference on vLLM as unverified; stored vectors must also be re-embedded through vLLM.

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
