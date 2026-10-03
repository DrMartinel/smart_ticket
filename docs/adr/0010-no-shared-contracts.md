# ADR-0010: No shared contracts package; schemas live where they are used

**Status:** Accepted
**Date:** 2026-09-28
**Departs from:** spec §2 rule 1 (`packages/contracts` as the single schema source)

## Context

Until now every schema lived in one workspace package, `packages/contracts`,
and both Python services imported it. That gave one definition of each shape,
but it tied the two services together at build time: each Docker image had to
copy a sibling package from outside its own directory, and a change to a type
only core-api uses (`Thresholds`, `ReviewAction`) still counted as a change to
ai-engine's dependency.

core-api and ai-engine are deployed separately. Compatibility between them
will be checked by cross-service integration tests, so a shared package is not
needed to keep them in step.

## Decision

`packages/contracts` is removed, and there is no `contracts` module in either
service. A contract is a type, so it is defined as a schema in the module that
uses it:

**core-api**

| Types | Module | Why there |
|---|---|---|
| `TicketIn` | `apps/tickets/request_schema.py` | The submit endpoint's request body. It replaces the old `TicketSubmitIn`, so Ninja validates the limits directly |
| `AIRunRequest`, `AIRunResponse`, `TicketMasked`, `TicketCategory`, the proposal union, the four signal models, the `/v1/embed` and `/v1/pii/detect` bodies (ADR-0012) | `infrastructure/dtos.py` | The schema of the calls to ai-engine, which `infrastructure/ai_engine.py` makes |
| `Branch`, `ReasonCode`, `ReviewQueue`, `RiskTier`, `KBArticleMeta`, `RoutingDecision` | `apps/tickets/utils/router.py` | The router's input and output |
| `Thresholds` and its parts | `config/settings/base.py` | The schema `thresholds.yaml` is parsed into at boot |
| `TrustScore` | `apps/tickets/utils/trust_scorer.py` | The scorer's output |
| `PIILevel` | `apps/tickets/utils/patterns.py` | Masking decides it |
| `ReviewAction`, `Verdict` | `apps/review/models.py` | Stored on `ReviewDecision` |
| `UserRole` | `apps/accounts/models.py` | Stored on `User` |

Types the router needs stay in plain-Python modules, never in a Django
`models.py`, so `router.py` stays importable without the ORM (CLAUDE.md
rule 1). The router imports `Thresholds` for type checking only: thresholds
always arrive as a parameter.

**ai-engine**

The wire types (`AIRunRequest`, `AIRunResponse` and everything nested in them,
plus `PIILevel` and `TicketCategory`) live in `schemas.py`, which imports
nothing else from ai-engine; the graph's state (`graph/state.py`) builds on
them. Putting them in `main.py` would create an import cycle, since the graph
needs them and `main.py` imports the graph. ai-engine defines no `Branch`,
`ReasonCode`, `RoutingDecision` or `TrustScore`: it has no authority to route
(ADR-0001) or to score itself (ADR-0003).

The TypeScript generator is `services/core-api/scripts/gen_typescript.py`,
reading core-api's schemas, because the web client only talks to core-api.

## Consequences

- The wire shapes are defined twice, once per service. **Until the
  cross-service integration tests exist, nothing catches drift between them.**
  Drift does not fail loudly: a renamed field is a 422 on every ticket, and a
  changed default (`quote_applicable`, `degraded_reason`) lets a degraded run
  look healthy to the router. Change both sides in the same PR.
- An invalid ticket submission is now rejected by Ninja's own body
  validation. The status is still 422; the body is Ninja's `{"detail": [...]}`
  instead of a JSON string under `detail`.
- The Docker build context is still the repo root, because of the shared
  `uv.lock` (and, for core-api, `infra/migrations/sql`). Giving each service
  its own lockfile is a separate step.
- `requirement.md` still describes `packages/contracts`. The spec records
  intent; this ADR records where the code departs from it and why.
