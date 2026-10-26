# Implementation status

Component-by-component state against [`requirement.md`](../requirement.md) (Architecture Specification v2), including known gaps. Written to be honest rather than flattering — a "✅" here means *verified working*, not *code exists*.

**Last verified through the UI:** 2026-07-29, against the full stack when it still ran Ollama (`qwen3.5:9b`, `qwen3:8b`, `bge-m3`). A ticket submitted through the UI reached the LLM, produced an auto-reply proposal, and was correctly held back by the negation check.

**Last verified through the eval harness:** 2026-10-04, on vLLM (Qwen3-8B-AWQ, bge-m3, bge-reranker-v2-m3) and Jev (`jev-1.13.0`). The harness masks each ticket with core-api's own `mask()` and calls ai-engine's `/v1/analyze` directly; the UI, Celery and the router's live execution were not part of it ([`evals/HISTORY.md`](../evals/HISTORY.md)).

---

## Summary

| | |
|---|---|
| Spec phases complete | **P0, P1** |
| Phase in progress | **P2** — calibration scripts ready, awaiting ≥500 shadow pairs |
| Unit tests | **503 passing** (247 core-api, 256 ai-engine), 2026-10-04 |
| Eval suites | 9 files, 26 tests. Last full run (2026-10-14 (2), `rerank_choice.v1`, `category.v2`): every gate it measured passes (recall@5 0.924, auto-reply precision 0.992, per-category F1 ≥ 0.90); end-to-end ran in two parts after DeepSeek's balance ran out (154 of 157 auto-replies right). See [`evals/HISTORY.md`](../evals/HISTORY.md) |
| Masking + router branch coverage | **100%** (`make coverage`) — the spec §14 P0 exit condition |
| Operating mode | `SHADOW_MODE=true` — router decides, humans still handle everything |

---

## By spec section

| § | Component | Status | Notes |
|---|---|---|---|
| §2 | Schema contracts | ⚠️ Changed | No shared package (ADR-0010): each schema lives in the module that uses it; TS types generated from core-api. Cross-service integration tests not written yet, so wire drift is unguarded |
| §3.1 | Ticket / embedding / quarantine schema | ✅ | Table + column names mirror the spec DDL exactly via `db_table`; keys are UUIDs, not the spec's `BIGSERIAL` (ADR-0011) |
| §3.1 | PII quarantine **write** path | ✅ | AES-GCM, key from env, 72 h TTL, expiry task on Celery beat |
| §3.1 | PII quarantine **read** path + access log | ✅ Unit-tested, browser-checked | Phase 2 F5: `POST /api/tickets/{id}/quarantine/reveal` for security, the holder of a claimed review item, or the assignee; credentials for security only. The access-log row, the decrypt and the `pii_revealed` audit row share one transaction; `pii_access_log` is append-only (trigger). Hourly limit `pii_reveal.max_per_user_per_hour`. Security reads and exports the log at `/security/access-log`. Checked locally 2026-10-17 on a seeded ticket. See [Gap 1](#gap-1-pii-quarantine-read-path) |
| §3.2 | KB schema + `auto_reply_allowed` governance | ✅ | DB `CHECK` enforces a named approver; every flip writes `kb_authority_log` |
| §3.3 | `ai_runs`, `routing_decisions` | ✅ | `thresholds_used` snapshot written on every decision |
| §3.4 | Review queue, decisions, eval candidates | ✅ | Overrides auto-create `eval_candidates` (§12.4 loop verified live) |
| §3.5 | Few-shot pool, incidents, append-only audit | ✅ | `REVOKE UPDATE, DELETE ON audit_log` applied in SQL migration |
| §4 | Discriminated-union contracts, `proposed_` prefixes | ✅ | `LLMProposalEnvelope` as `RootModel`, `frozen=True` on `TicketMasked`; the classify reply is decoded against the proposal's JSON Schema on vLLM |
| §5 | Masking engine (inline, two-tier) | ✅ | 100% branch coverage; regex tier-1 short-circuits before any LLM call. NER (`pii_ner.v2`, greedy) runs in ai-engine (ADR-0012); NER spans over `masking.ner_max_share` of the text make the ticket `mask_failed` |
| §6 | LangGraph pipeline | ✅ | Refuse-before-LLM verified; graph is acyclic (no LLM retry). Nodes: injection → draft_answer → hybrid_retrieve → candidate_pool → rerank → classify_category → select_fewshots → infer → validate → emit_signals |
| §6.3 | Retrieval: vector + RRF, pages | ✅ | Vector search on the ticket only; BM25 on the ticket removed with the `bm25_keyword_hit` trust feature (ADR-0020, Proposed). pg_search (ADR-0013) and its index stay. First 10 pages, one chunk each. RRF k=60; no threshold on fused rank (ADR-0005) |
| §6.3 | Cross-encoder shortlister + link expansion | ✅ | bge-reranker-v2-m3 on vLLM (`SHORTLIST_PROVIDER=vllm`; `lexical`, for CI, folds Vietnamese diacritics), scoring against the ticket. Each of the 10 candidate pages brings its best-fused chunk and its 2 chunks nearest the drafted answer; the pages of its top 3 seed link expansion, and it picks Jev's shortlist of 15. Associations come from `kb_article_associations`, one source at a time (`ASSOCIATION_SOURCE`, ADR-0018): **`entity_graph` shipped** since 2026-10-12 (an offline DeepSeek build of problem-to-fix pointers; ties `authored_link` under HyDE, 0.816 vs 0.810 recall@3, at half the batch). Since 2026-10-13 the build writes its rows itself (ADR-0025, `load_associations` removed): unit-tested, not yet run against the Dockerized Postgres |
| §6.3 | Drafted answer (HyDE, ADR-0021, ADR-0022) | ⚠️ DeepSeek-measured | `draft_answer` writes the documentation passage that would answer the ticket; retrieval fuses vector search on the ticket with BM25 and vector search on the draft (no BM25 on the ticket, ADR-0020). Production drafts on DeepSeek (masked ticket); the template ships `vllm`. Recall@5 0.906-0.914 on 500 tickets with DeepSeek drafting, 0.816 recall@3 with Qwen. A failed or malformed draft is a 500 → HITL (about 1 in 350) |
| §6.3 | Reranker: Jev, hosted (ADR-0015, ADR-0026 Proposed) | ⚠️ Uncalibrated, no eval run | One choice question over the shortlist plus `none` (`rerank_choice.v1`); an auto-reply must cite Jev's choice at confidence ≥ 0.9 🔧 ([TODO](TODO.md) item 13). Its top 5 go on, one page per slot (`RERANK_TOP_N_PER_PAGE=1`). `retrieval.floor` 0.30 is on its scale but chosen from the golden set; see [Gap 3](#gap-3--retrievalfloor-is-uncalibrated). Its API failed four times on 2026-10-04 and three times with TLS errors on 2026-10-11/12, each a ticket for a human; its credit ran out twice under eval load |
| §8 | Category: Jev's choice (ADR-0017, Proposed) | ✅ Full run | `classify_category` asks Jev one choice question (`category.v2`); the router routes on it, below `classification.min_confidence` to a human. Per-category F1 ≥ 0.90 on 523 tickets (2026-10-14 (2)), on the set `category.v2` was written against |
| §6.4 | Validator (quote → fuzzy → in-top-k → negation) | ✅ | Negation check verified catching a real `negation_mismatch` live; also checks a clarify proposal's options were shown |
| §7 | Trust scorer, outside ai-engine | ⚠️ Uncalibrated | Works, but coefficients are a hand-set prior — see [Gap 2](#gap-2-trust-score-is-an-uncalibrated-prior) |
| §8 | Switch router — pure `Router`, hard gates ordered | ✅ | Every branch unit-tested with no DB/LLM/network |
| §8 | `clarify` branch (ADR-0016, ADR-0023, Proposed) | ⚠️ Unit-tested only | A live chat ticket asks "Which of these is closest to what you need?" with buttons core-api builds from Jev's top 5 (pages whose per-page yes/no score, asked only for a validated clarify, is within 0.1 🔧 of the best, up to 5; ADR-0023 amended 2026-10-14) and "None of these"; the answer is masked like a ticket, appended as `Requester clarified: …`, and the pipeline runs again; `propose.v9` treats it as the reading chosen. One question, then a human (`clarify_round_cap`); unanswered after 60 min 🔧, a ticket is offered. Form tickets and shadow mode: a review item in the `clarification` queue. Not yet run on a live ticket, and no eval covers the second run |
| §8.2 | Shadow mode | ✅ | Same `route()` in both modes |
| §9 | Incident detector (adaptive baseline + 3σ) | ✅ | Concurrent-worker dedup serialized by a Postgres advisory lock |
| §10.1 | Circuit breaker | ❌ Removed | Deliberately dropped to simplify; every LLM failure is `all_llm_down` → HITL |
| §10.2 | Per-ticket budget + daily cost ceiling | ⚠️ Partial | Per-ticket budget removed; daily ceiling still enforced in core-api |
| §10.3 | Failure-mode table — always degrade to a human | ✅ | Including the embedding path (fixed 2026-07-28) |
| §11.1 | Dashboard metrics | ✅ | `reopen_rate_after_autoreply`, `approve_rate_per_reviewer`, `median_time_spent` all implemented |
| §11.2 | `trace_id` propagation | ⚠️ Partial | Threaded through app + audit log; no LangSmith/Langfuse export — see [Gap 4](#gap-4-no-external-trace-backend) |
| §12 | Eval harness, golden set, CI gate | ✅ | 174 synthetic cases (150 at the §12.1 distribution, plus 24 edge cases); the harness masks tickets with core-api's `mask()`; every full run is recorded in `evals/HISTORY.md` and `evals/history/` |
| §13 | Centralized thresholds | ✅ | `thresholds.yaml` is the only source; loaded as a validated Pydantic model at boot |
| — | Configurable ticket lifecycle (ADR-0028, Accepted 2026-10-17) | ⚠️ Unit-tested, probed live | Workflows, statuses, transitions with field rules, custom fields with events, and actions (fields, assignment, SLA, moves, email, webhook, n8n callback, approval) on Celery with retry and a watchdog. Pipeline status writes go through `lifecycle.system_move`. A live edge-case probe on 2026-10-15 found 13 classes of defect, all fixed with regression tests (ADR-0028 amendment). admin-console has a ticket list, a board per workflow, a ticket page with its timeline and assignment, and workflow and stage settings (not browser-checked yet); no approvals screen, no real n8n or SMTP run |
| — | Server-side role enforcement (phase 2 PRE-1) | ✅ Unit-tested | Every route but sign-in, refresh, sign-out and the lifecycle callback carries `require_role`; `test_every_route_is_gated` fails on a new one without it. Refusals are 403 `role_not_allowed` with one `access_denied` audit row per user, route and method a minute. An employee reading someone else's ticket gets 404. Runbook approval and execution need a technician or manager, at the route and in `RunbookExecution` |
| — | Sign-in through Keycloak (phase 2 F13, ADR-0032) | ✅ Unit-tested, checked against the dev Keycloak | Both apps sign in with OIDC code + PKCE; core-api verifies the ID token, takes role, capabilities (ADR-0031) and `/it/<team>` groups from it, creates or links the user, and starts the ADR-0029 session below. Back-channel logout and `identity_sync` (every `identity.sync_interval_minutes`) end a leaver's sessions; a failed Keycloak read changes nobody. Local password sign-in is for break-glass managers only, refuses everyone else with the same 401, locks after `identity.local_max_failures`, and alerts security. Checked 2026-10-17 with the compose `keycloak` (profile `sso`): sign-in, sync against the real admin API, a disabled user losing access, the no-access page. No production realm yet |
| — | Notifications (phase 2 F4, ADR-0033) | ✅ Unit-tested, browser-checked | `Notifier.emit` writes one message per recipient and channel in the event's transaction, from the matrix, preferences and mandatory cells, in each user's language, from masked text only; email and signed webhooks go out after commit on Celery with retries, a 60 s sweep and a daily purge. Emitted today: assignment (`ticket.assigned`/`reassigned`/`unassigned`), `approval.requested` (closes TODO 14.3), `identity.break_glass_used`, and `security.alert` at the F5 and F13 alert sites. Bell and panel in both apps; my settings, the matrix, the delivery log and webhooks in the admin console. Checked locally 2026-10-26 against the dev Keycloak and the console email backend. No real SMTP relay or webhook host yet; F1/F2/F3/F6–F10 events wait for their features |
| — | Sign-in sessions (ADR-0029, Accepted 2026-10-17) | ✅ Browser-checked | Access token in memory, rotating refresh token in an httpOnly cookie per frontend, reuse detection, immediate revocation on sign-out. Checked in both frontends on 2026-10-15: sign-in, reload restore, sign-out, a requester refused by the admin console |

---

## Known gaps

Each gap below has a corresponding actionable entry in [`TODO.md`](TODO.md) — update both together.

### Gap 1 — PII quarantine read path (closed 2026-10-17, phase 2 F5)

Closed by F5. `PiiReveal.reveal()` (`apps/tickets/utils/pii_reveal.py`) is the only caller of `crypto.decrypt()`, and `test_decrypt_has_one_caller` keeps it that way. What it replaced:


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

Every run shortlists, then reranks (ADR-0015): the `bge-reranker-v2-m3` cross-encoder on vllm-rerank (`SHORTLIST_PROVIDER=vllm`; `lexical` in CI) shortlists the candidates plus link-expanded chunks, and Jev, the reranker, ranks its top 15 with one choice question (ADR-0026). `retrieval.floor = 0.30` is on Jev's scale (🔧): chosen from golden-set data, not fitted. The trust coefficients were hand-set for the cross-encoder's scores, not Jev's. Treat refusal and trust behaviour as uncalibrated.

Since ADR-0017 (Proposed, 2026-10-04) Jev also chooses the ticket's category, and auto-route and clarify act on it below `classification.min_confidence` = 0.65 (🔧, from one probe on the golden set) only via a human. Full run 2026-10-14 (2) on `category.v2`: every category ≥ 0.90; a held-out check is still owed ([TODO.md](TODO.md) item 11).

See [TODO.md](TODO.md) item 4.

### Gap 4 — No external trace backend

`trace_id` is minted per request, propagated through core-api → Celery → ai-engine, and stored on `audit_log.trace_id`, so a ticket's history is reconstructable from the database. The spec §11.2 idea of jumping from a business log line into a full LLM trace needs a LangSmith/Langfuse exporter, which is not wired up.

### Gap 5 — The eval gates on `main` are not all measured together

Full runs are in [`evals/HISTORY.md`](../evals/HISTORY.md); runs before the 2026-10-01 baseline are in [`evals/HISTORY-archive.md`](../evals/HISTORY-archive.md).

- **Retrieval** is gated on **recall@5** since 2026-10-12 (spec §12.2; was recall@3), on the 500-ticket set: **0.906-0.914** with HyDE (DeepSeek drafting), the entity graph and one page per slot (`evals/HISTORY.md` 2026-10-12 (5)); recall@3 0.872-0.876. On the original 60, 0.917 throughout; still missed g012, g048, g055, g056 ([`TODO.md`](TODO.md) item 9). The gate change awaits review by someone other than its author (rule 9). `baselines/baseline.json` still holds old sample numbers and `report.py --compare` still reads recall@3.
- **Auto-reply precision** is **0.992** (119/120, 2026-10-14 (2)) over the ADR-0027 approvals; the false one is g156, labelled `clarify`. It was 0.944 (34/36) on 2026-10-04 (8).
- **Per-category F1** passes on Jev's choice (ADR-0017) with `category.v2`, every category ≥ 0.90 on 523 tickets (2026-10-14 (2)); on `category.v1` with the guides' categories the drafted tickets failed it (security 0.63).

**Do not lower a floor or drop a category to make CI green** — per-category F1 exists precisely so a rare category cannot hide behind a healthy average.

---

## Environment caveat: the UI path has not run on vLLM

The UI verification below ran on Ollama. The system now uses self-hosted vLLM (ADR-0009), reached only through ai-engine: core-api's PII NER and embeddings go through ai-engine's `/v1/pii/detect` and `/v1/embed` (ADR-0012). vLLM and Jev are exercised by every full eval run, masking included, on one RTX 3060 (the three vLLM servers share it; fractions and start order in [`onboarding.md`](onboarding.md) step 2). What has not run on them: submitting through the UI, the Celery task, and executing a decision.

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
