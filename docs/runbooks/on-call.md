# On-call runbook

## Circuit breaker opened (`ai-engine/llm/client.py`)

**Alert fires when:** LLM failure rate > 20% over a trailing 5-minute
window (`CIRCUIT.failure_threshold`).

**What this means operationally:** every ticket that would have gone
through `infer` is now falling back to Ollama, and if that also fails,
straight to HITL with `degraded_reason="all_llm_down"`. HITL queue depth
will rise sharply within minutes. This is a staffing signal, not just a
technical one — see spec §10.1.

**Actions:**
1. Check `docker compose logs ai-engine` / provider status page for the
   configured cloud LLM.
2. Check `daily_cost_ceiling_usd` — if the circuit opened because of budget
   exhaustion rather than provider errors, that's a different problem
   (see below).
3. Notify the review queue owner so extra reviewers can be pulled in — the
   circuit stays open for `open_duration` (10 min) before trying 10% of
   traffic again (half-open).
4. If the underlying provider outage is prolonged, consider manually
   flipping `SHADOW_MODE` considerations aside — HITL already receives
   everything degraded, so no config change is needed for tickets to keep
   flowing; this is a "add people" incident, not a "change code" incident.

## Daily cost ceiling exceeded (`budget.daily_cost_ceiling_usd`)

**What this means:** AI is switched off for the rest of the day; every
ticket routes to HITL with `degraded_reason="budget_exceeded"`.

**Actions:**
1. Check `ai_runs` for a spike in `tokens_in`/`llm_calls` per ticket —
   this is the signature of an adversarial ticket designed to induce a
   retry loop (spec §10.2).
2. If it's legitimate volume, that's a capacity-planning conversation for
   tomorrow's ceiling, not a same-day override — raising the ceiling
   live during an incident should not be a one-person decision.

## `pgvector` degraded / slow

**What this means:** retrieval falls back to BM25-only, and *every* ticket
routes to HITL (spec §10.3: "retrieval kém = không đủ tin để auto" — weak
retrieval never earns enough trust to automate). This is expected,
self-limiting behavior, not a bug.

**Actions:**
1. Check Postgres `pg_stat_activity` for long-running queries against
   `kb_chunks`/`ticket_embeddings`.
2. Confirm the HNSW indexes still exist and are being used
   (`EXPLAIN ANALYZE` a known vector query).

## `ai-engine` unreachable entirely

**What this means:** tickets are still accepted normally (**fail open
toward humans**, per spec §10.3) and all go to HITL with
`degraded_reason="ai_engine_unavailable"`. No tickets are lost.

**Actions:**
1. `docker compose ps ai-engine` — check it's up and passing health
   checks.
2. This is the safest failure mode in the system; it is not an emergency
   for ticket handling, only for the backlog it creates.

## DB read-only

**What this means:** the ticket-submission endpoint returns `503` rather
than silently dropping data (spec §10.3: "từ chối rõ ràng hơn là mất im
lặng" — an explicit refusal beats a silent loss).

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
