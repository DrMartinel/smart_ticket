# Recipe: a signal or failure reason that crosses into core-api

ai-engine proposes and core-api decides. Anything ai-engine learns only matters once
it reaches core-api through the wire contract, which each service holds its own
copy of (ADR-0010). This recipe is for a new
`TrustSignals` field, a new `AIRunResponse` field, or a new failure reason.

Open these before writing: `trust.py` and `ai_request.py` in both
`services/ai-engine/src/ai_engine/contracts/` and `services/core-api/contracts/`,
core-api's `contracts/enums.py` (`ReasonCode`), `graph/nodes/emit_signals.py`, `main.py`,
`services/core-api/apps/tickets/utils/pipeline.py`,
`services/core-api/apps/tickets/utils/trust_scorer.py`, and `router.py`.

## Order of work

Do the steps in this order. Each one compiles on top of the one before.

1. **Contract.** Add the field in **both** copies, identically —
   `evals/suites/test_contract_parity.py` fails otherwise. Give it a default, because
   persisted rows written before the change still have to deserialize.
   `GenerationSignals.quote_applicable` is the worked example: the comment explains
   what the field distinguishes, and the default keeps old rows loading. Constrain
   the value with `Field(ge=…, le=…)` where the range is known.
2. **TypeScript types.** Regenerate them, and never hand-edit `generated.ts`:
   ```bash
   uv run --package core-api python services/core-api/scripts/gen_typescript.py
   ```
3. **ai-engine state and producer.** Add the state field under its producing node,
   and set it in that node (see `node.md`).
4. **Forward it.** `EmitSignalsNode.__call__` builds `TrustSignals`, so copy the state
   field in there. If the field belongs on `AIRunResponse` instead, set it in
   `main.py`'s `analyze`.
5. **core-api consumer.** Choose **one**:
   - Trust score feature: goes in `trust_scorer.py`. The coefficients are a
     hand-set prior, so a new feature is a calibration question for the user.
   - Hard gate: goes in `router.py`. The function has to stay pure, and any new
     threshold goes in `thresholds.yaml`, which is passed in (CLAUDE.md rules 1 and 2).
   - Log-only field: add no consumer, and say "log-only" in the contract comment.
6. **Reviewer UI.** If a reviewer needs to see the value, it goes in
   `services/web/components/TrustSignalsPanel.tsx`.

## A new failure reason

1. Add a `ReasonCode` member in core-api's `contracts/enums.py`, under the right heading
   (hard gates, trust-based, or degraded). The dashboard is built on this enum, so
   free text doesn't show up there.
2. In ai-engine, return `degraded_reason=` with **exactly** that member's value and
   keep outputs at their safe defaults. `infer.py`'s `"all_llm_down"` is the precedent.
   Using `ReasonCode.X.value` is better still (refactor move #12).
3. In core-api, map it in `apps/tickets/utils/pipeline.py` next to the
   `resp.degraded_reason == ReasonCode.ALL_LLM_DOWN.value` branch, so the ticket
   reaches HITL under that code rather than a generic one.
4. Add a test on the ai-engine side that pins the exact string (see
   `test_infer.py::test_all_llm_down_maps_to_degraded_reason_all_llm_down`), and a
   core-api test that the code reaches HITL.

## Limits

- `llm_self_confidence` never becomes a feature, a gate, or a tiebreaker (ADR-0003).
  Its tests will fail if it does.
- `TrustSignals.policy` from ai-engine is **informational**. The auto-reply authority
  check is core-api's own KB read (ADR-0002). Don't make routing depend on
  ai-engine's policy block.
- A refuse-before-LLM run never reaches `validate`. Make sure the new field's default
  is honest for that path, and check it with `make_state()` and no overrides.

## Done when

- [ ] The contract field has a default and the TS types are regenerated.
- [ ] The producer sets the value and `emit_signals` or `main.py` forwards it.
- [ ] The core-api consumer is chosen deliberately, or the field is marked log-only.
- [ ] Any new reason code has a `ReasonCode` member, is mapped in `pipeline.py`, and is pinned by tests on both sides.
- [ ] `uv run pytest` passes for the whole workspace, not just ai-engine.
