# ADR-0004: `ai-engine` is a separate service from `core-api`

**Status:** Accepted
**Date:** 2026-07-27

## Context

Recorded now so that six months from now nobody has to reverse-engineer
why there are two Python services instead of one Django app with a
LangGraph module bolted on.

## Decision

`ai-engine` (FastAPI + LangGraph) is deployed independently from
`core-api` (Django + Django Ninja). They communicate over HTTP
(`POST /v1/analyze`), not via shared Python imports, aside from the
`contracts` package.

## Reasons, in order of weight

1. **Structural permission boundary (the load-bearing reason).**
   `ai-engine` connects to Postgres with a role
   (`ai_engine_ro`) that has `SELECT`-only grants on `kb_articles`,
   `kb_chunks`, and `fewshot_examples`, and no grants at all on `tickets`,
   `routing_decisions`, `ai_runs`, or `audit_log`. It is not merely
   *discouraged* from writing business data by code review — it is
   physically unable to, at the database layer (see
   `infra/migrations/sql/`). This is the reason splitting the service is
   worth the operational cost; every other reason below is secondary.
2. **Independent dependency tree.** LangChain/LangGraph move fast and
   break things; pinning them tightly against Django's own dependency
   graph would force synchronized upgrades neither side wants.
3. **Different scaling profile.** `ai-engine` wants RAM for the reranker
   model; `core-api` wants I/O concurrency. Coupling their deployment
   couples their scaling knobs for no benefit.
4. **Independent deploys.** A prompt or retrieval change ships without
   restarting the API gateway that employees are actively submitting
   tickets through.

## Consequences

- An extra network hop and an extra service to operate (health checks,
  logs, its own Docker image).
- `contracts` becomes load-bearing infrastructure: both services must
  agree on wire schema, so it is versioned and tested independently (see
  ADR referenced in spec §2 rule 1).
