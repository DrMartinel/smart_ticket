# On-call runbook

## Circuit breaker opened (`ai-engine/core/llm/client.py`)

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
1. Check Ollama on the host: `curl -s localhost:11434/api/tags`.
2. Confirm `bge-m3` is present (`ollama list`) — a missing model returns an
   error, not a timeout.
3. If Ollama is healthy from the host but the worker still fails, this is
   almost certainly container→host networking, not Ollama (see below).
4. `EMBEDDING_PROVIDER=stub` is a legitimate emergency lever: it keeps the
   pipeline flowing with deterministic hash embeddings. Retrieval quality
   collapses, so *everything* lands in HITL — acceptable for a short
   outage, not as a standing configuration.

## Containers cannot reach Ollama on the host

**Symptom:** `httpx.ConnectTimeout` from `worker`/`ai-engine`, while
`curl localhost:11434` from the host succeeds. Every ticket degrades to
HITL via `embedding_unavailable` or `ai_engine_unavailable`.

**What this means:** Ollama runs on the host, not in Docker. Containers
reach it via `host.docker.internal`, which compose maps to the bridge
gateway. A host firewall that blocks the Docker subnet silently breaks
this — the containers are healthy, Ollama is healthy, and only the path
between them is dead.

**Diagnosis:**
```sh
docker compose exec worker sh -c \
  'curl -s -m 5 -o /dev/null -w "%{http_code}\n" http://host.docker.internal:11434/api/tags'
```
`000` with a ~5 s hang means blocked/dropped, not refused.

**Actions — pick one:**

*A. Sidestep the host network entirely (no sudo).* Run Ollama as a compose
service on the same network, re-using the host's already-downloaded models:
```sh
docker compose --profile local-llm up -d
# then in infra/.env:  OLLAMA_BASE_URL=http://ollama:11434
```
The model store is bind-mounted read-only (`OLLAMA_MODELS_DIR`, default
`/usr/share/ollama/.ollama/models`), so nothing re-downloads. Note both
Ollamas share one GPU — if VRAM runs short, stop the host service.

*B. Open the firewall (needs sudo).*
1. Confirm Ollama binds beyond loopback: `OLLAMA_HOST=0.0.0.0` (a
   `127.0.0.1`-only bind is unreachable from any container).
2. Allow the Docker bridge range to the Ollama port, e.g. with ufw:
   ```sh
   sudo ufw allow from 172.16.0.0/12 to any port 11434 proto tcp
   ```
3. Re-run the diagnosis above; expect `200`.

## `MASK_FAILED` flood — every ticket lands in the mask_failed queue

**What this means:** tier-2 NER (Ollama) is failing for every ticket, and
masking is correctly refusing to treat "I couldn't check" as "it's clean"
(spec §5.2). The system is behaving as designed; the queue is the symptom,
not the bug.

**Known causes, in order of likelihood:**
1. **Ollama returning HTTP 500 under load.** Several models sharing one
   GPU will OOM-thrash. Check `ollama ps` for co-resident models and the
   Ollama logs for 500s. Mitigation is capacity, not code.
2. **Model unavailable.** `qwen3:8b` (`OLLAMA_NER_MODEL`) not pulled.
3. **Timeout too short for a cold start.** The per-call ceiling is
   `OLLAMA_TIMEOUT_SEC` (120s default). A cold Ollama model load alone can
   take 15–20s, so a low value here reports "provider down" for what is
   really "provider still warming up" — this was the original cause of a
   flood, back when the NER budget was a hardcoded 3s. If you raise it
   past 120, raise `budget.max_latency_sec` in `thresholds.yaml` **and**
   the gunicorn `--timeout` in `docker-entrypoint.sh` too: masking runs
   inline in the submit request, so gunicorn reaping the worker first
   turns a clean MASK_FAILED into a 502 and loses the ticket.
4. **Response-shape drift.** `format="json"` guarantees valid JSON, *not* a
   top-level array — models routinely wrap it (`{"found": [...]}`). The
   parser unwraps the first list value it finds; a model that returns some
   genuinely different shape will fail closed to `MASK_FAILED`. Check the
   `masking: Ollama NER failed (...)` warning — it logs the offending
   payload verbatim.

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
