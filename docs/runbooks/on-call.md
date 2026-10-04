# On-call runbook

## LLM provider failing (spike in `all_llm_down`)

**What this means:** the chat model is failing. There is no retry and no
circuit breaker, so every ticket that reaches `infer` makes one call, waits
for it to fail (up to `MODEL_CONNECT_TIMEOUT_SEC` if the provider is
unreachable, up to `MODEL_TIMEOUT_SEC` if it hangs) and goes to HITL with
reason code `all_llm_down`. HITL queue depth will rise sharply within
minutes. This is a staffing signal, not just a technical one.

**Actions:**
1. Check `docker compose logs ai-engine` — each failure is logged with its
   cause — and vllm-chat (or OpenAI's status page).
2. Notify the review queue owner so extra reviewers can be pulled in.
3. No config change is needed for tickets to keep flowing — HITL already
   receives everything degraded. This is an "add people" incident, not a
   "change code" incident.

## Daily cost ceiling exceeded (`budget.daily_cost_ceiling_usd`)

**What this means:** AI is switched off for the rest of the day; every
ticket routes to HITL with `degraded_reason="budget_exceeded"`.

**Actions:**
1. Check `ai_runs` for a spike in `tokens_in`/`tokens_out` per ticket.
   ai-engine makes at most one LLM call per ticket and enforces no
   per-ticket token budget, so a spike means oversized inputs or runaway
   generations (bounded only by `CLOUD_MAX_OUTPUT_TOKENS`).
2. If it's legitimate volume, that's a capacity-planning conversation for
   tomorrow's ceiling, not a same-day override — raising the ceiling
   live during an incident should not be a one-person decision.

## Jev failing (spike in `ai_engine_unavailable` with ai-engine up)

**What this means:** Jev, the hosted model that reranks the shortlist and
chooses the category (ADR-0015, ADR-0017), is failing requests. ai-engine
does not retry and has no fallback: falling back to the cross-encoder's
order would compare its scores with a floor set on Jev's, and falling back
to the LLM's category would hide the outage. Each affected ticket gets a
500 from ai-engine and goes to HITL as `ai_engine_unavailable`. Jev's API
has failed with TLS errors and 520s in bursts (four on 2026-10-04).

**Actions:**
1. `docker compose logs ai-engine` shows the failing call
   (`httpx.HTTPStatusError`, `ConnectError`) in the traceback.
2. Check `JEV_API_KEY` is set in ai-engine's environment, and TypeSafe's
   status. A 429 is a rate limit, not an outage.
3. Like an LLM outage, this is an "add people" incident: tickets keep
   flowing to humans. Do not switch the reranker or the category source to
   keep automation running; that changes what every threshold means.

## `pgvector` or BM25 queries failing / slow

**What this means:** retrieval has no fallback. A failing vector or BM25
query raises in ai-engine, which answers 500, and the ticket goes to HITL as
`ai_engine_unavailable`; a query slow enough to outlast
`budget.max_latency_sec` ends the same way from core-api's side. Vector-only
or BM25-only retrieval is never substituted: a channel that silently stopped
working is exactly the failure ADR-0013 was written after.

**Actions:**
1. Check Postgres `pg_stat_activity` for long-running queries against
   `kb_chunks`/`ticket_embeddings`.
2. Confirm the HNSW indexes still exist and are being used
   (`EXPLAIN ANALYZE` a known vector query).

## Embedding provider unavailable (`degraded_reason="embedding_unavailable"`)

**What this means:** core-api could not embed the ticket, so incident and
duplicate detection could not run. The ticket routes to HITL with
`ReasonCode.EMBEDDING_UNAVAILABLE` (spec §10.3 — degrade toward a human).

**Why this one deserves its own entry:** the embedding call happens in
`process_ticket` *before* the ai-engine call, and it is the only remote
call in that early stretch. Before this path had a handler, an embedding
outage raised straight out of the Celery task and left tickets frozen at
`status="new"` with no `RoutingDecision` and no `ReviewItem` — invisible
to every queue and dashboard. If you ever see tickets stuck at `new` with
no routing row, look here first.

**Actions:**
core-api embeds through ai-engine (ADR-0012), so either can be the cause.

1. Check ai-engine is reachable from the worker:
   `docker compose exec worker sh -c 'curl -s -m 5 $AI_ENGINE_URL/healthz'`.
2. Check the embedding server behind it: `docker compose --profile vllm ps vllm-embed`,
   `docker compose logs vllm-embed`, and `docker compose logs ai-engine`
   for `embedder failed`.
3. A wrong-width vector raises `ValueError` and lands here too — check that
   ai-engine's `EMBED_MODEL` is a 1024-dim model (`bge-m3`).
4. `EMBEDDING_PROVIDER=stub` **on ai-engine** is a legitimate emergency
   lever (core-api has no embedder of its own, ADR-0012): it keeps the
   pipeline flowing with deterministic hash embeddings. Retrieval quality
   collapses, so *everything* lands in HITL — acceptable for a short
   outage, not as a standing configuration.

## `MASK_FAILED` flood — every ticket lands in the mask_failed queue

**What this means:** tier-2 NER (ai-engine's `/v1/pii/detect`, on vLLM) is failing for every ticket, and
masking is correctly refusing to treat "I couldn't check" as "it's clean"
(spec §5.2). The system is behaving as designed; the queue is the symptom,
not the bug.

**Known causes, in order of likelihood:**
1. **ai-engine down or unreachable from core-api.** Check
   `docker compose exec core-api sh -c 'curl -s -m 5 $AI_ENGINE_URL/healthz'`.
   `docker compose logs ai-engine` shows `PII NER failed: <ErrorClass>` when
   it is up but the model call fails. The text is never logged, by design.
2. **vllm-chat down or out of memory.** It shares the GPU with vllm-embed and
   vllm-rerank through fixed `*_GPU_UTIL` fractions. Check
   `docker compose logs vllm-chat` for OOM or 5xx. Mitigation is capacity,
   not code.
3. **Model unavailable.** ai-engine's `CHAT_MODEL` does not match the
   model vllm-chat is serving — the server rejects the request.
4. **Timeout too short for a cold start.** The per-call ceiling is
   `MODEL_TIMEOUT_SEC` (120s default). A cold model load alone can
   take 15–20s, so a low value here reports "provider down" for what is
   really "provider still warming up" — this was the original cause of a
   flood, back when the NER budget was a hardcoded 3s. If you raise it
   past 120, raise `budget.max_latency_sec` in `thresholds.yaml` **and**
   the gunicorn `--timeout` in `docker-entrypoint.sh` too: masking runs
   inline in the submit request, so gunicorn reaping the worker first
   turns a clean MASK_FAILED into a 502 and loses the ticket.
5. **Response-shape drift.** The request pins a JSON Schema, so the reply
   should be `{"spans": [...]}`. ai-engine validates it, and a server that
   ignores the schema, or a reply with no content, comes back to core-api
   as a 502 and fails closed to `MASK_FAILED`. Neither service logs the
   ticket text or the model's reply (for NER the reply *is* the PII): look
   for `PII NER failed: <ErrorClass>` in ai-engine and
   `masking: LLM NER failed (...)` in core-api.
6. **Over-masking, not failure.** If the warning is
   `masking: NER covered 0.xx of the text (max 0.70)`, NER answered but
   masked more of the ticket than `masking.ner_max_share` allows, so the
   ticket goes to a human rather than on with its substance removed. A
   flood of these means the NER prompt regressed (`PII_NER_PROMPT_VERSION`);
   `evals/suites/test_masking.py` measures it.

**Do not** "fix" this by treating NER failure as no-PII-found. That inverts
the one safety property this stage exists to guarantee.

## `ai-engine` unreachable entirely

**What this means:** tickets are still accepted normally (**fail open
toward humans**, per spec §10.3) and all go to HITL with
`degraded_reason="ai_engine_unavailable"`. No tickets are lost.

**Actions:**
1. `docker compose ps ai-engine` — check it's up and passing health
   checks.
2. This is the safest failure mode in the system; it is not an emergency
   for ticket handling, only for the backlog it creates.

## Mass incident declared (`ReasonCode.MASS_INCIDENT`)

**What this means:** the detector saw similar tickets exceeding
`baseline + 3σ` for that category *and* at least `incident.min_count` (5)
within the window. Affected tickets are linked to a parent `Incident`,
escalated, and **skip the AI engine entirely** — no auto-reply is possible
during an outage (spec §9).

**Actions:**
1. Treat it as an outage first, tickets second. `incidents.baseline_rate`
   records what "normal" was at detection time, so the call is auditable
   after the fact.
2. Use the parent incident to notify every linked reporter once, with an
   ETA. That single broadcast — rather than 40 individually-generated,
   possibly-wrong answers — is the entire point of this branch.
3. **If you see two `Incident` rows for one real outage:** the dedup lookup
   is serialized by a Postgres advisory lock keyed on category, so
   concurrent Celery workers should converge on one row. Duplicates mean
   either the lock path regressed or the two batches genuinely differ in
   category — check `incidents.category` before merging by hand.

## DB read-only

**What this means:** spec §10.3 asks the submission endpoint to answer `503`
rather than silently dropping data ("từ chối rõ ràng hơn là mất im lặng" —
an explicit refusal beats a silent loss). **Not built:** there is no
read-only handling today, so a failed write surfaces as an unhandled
database error (a 500) on submit. The ticket is not stored either way;
the submitter sees an error, not a silent loss.

**Actions:**
1. Check whether this is a planned failover or an actual outage.
2. Do not add a "queue tickets in memory and retry" workaround under
   pressure — that reintroduces the silent-loss failure mode this design
   explicitly avoids.

## General principle

Every failure mode in this system degrades toward a human, never toward
an automated decision made with weaker signal. If you are ever tempted to
patch around a degraded state by loosening a threshold instead of fixing
the underlying failure, don't — read ADR-0006 first.
