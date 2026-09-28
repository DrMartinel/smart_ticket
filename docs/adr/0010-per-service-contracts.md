# ADR-0010: Each service holds its own copy of the schema contracts

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

core-api and ai-engine are deployed separately. The only thing they must
agree on is the JSON that crosses the wire: `AIRunRequest` and
`AIRunResponse`.

## Decision

`packages/contracts` is removed. Each service owns a copy:

| Service | Path | Contents |
|---|---|---|
| core-api | `services/core-api/contracts/` | Everything the old package had. Imports stay `from contracts.… import …`. |
| ai-engine | `services/ai-engine/src/ai_engine/contracts/` | Only the wire types and what they contain: `TicketMasked`, the proposal union, the four signal models, `PIILevel`, `TicketCategory`, `AIRunRequest`, `AIRunResponse`. |

ai-engine's copy is trimmed on purpose. It has no `Branch`, `ReasonCode`,
`RoutingDecision`, `Thresholds` or `TrustScore`. ai-engine has no authority to
choose a branch (ADR-0001) or to score itself (ADR-0003), so it now cannot
even name those types.

The TypeScript generator moved to `services/core-api/scripts/gen_typescript.py`
and reads core-api's copy, because the web client talks only to core-api.

## How drift is caught

Two copies of the wire types can drift apart, and the drift does not fail
loudly. A renamed field turns into a 422 on every ticket. A changed default
is worse: the field is left at its default (`quote_applicable=True`,
`degraded_reason=None`) and a degraded run looks healthy to the router.

`evals/suites/test_contract_parity.py` compares the full JSON schema
(validation and serialization mode, descriptions stripped) of every model in
ai-engine's copy with the model of the same name in core-api's copy, and the
values of the shared enums. It runs in the offline tier of `eval-gate.yml`,
on every PR. It also fails if a name is added to ai-engine's `__all__`
without a parity check, which forces the question of whether that type
belongs on the ai-engine side at all.

Rule: **a change to a wire type is made in both copies in the same PR.**

## Consequences

- One more place to edit for a wire change. The parity suite turns a missed
  edit into a red CI run instead of a silent production bug.
- The Docker build context is still the repo root. That is now because of
  the shared `uv.lock` (and, for core-api, `infra/migrations/sql`), not
  because of the contracts. Giving each service its own lockfile is a
  separate step.
- `requirement.md` still describes `packages/contracts`. The spec records
  intent; this ADR records where the code departs from it and why.
