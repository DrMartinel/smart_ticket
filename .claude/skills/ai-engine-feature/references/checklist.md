# ai-engine change checklist

Used by `/ai-engine-feature` (self-review) and `/ai-engine-review` (reviewing a diff).
Answer each item that applies to the change. **[regression]** means a hard rule or
safety invariant: it must be fixed before merge. **[convention]** means the house
style: fix it unless there is a stated reason not to.

Rules live in `ai-engine-conventions.md` (ai-engine) and
`.claude/skills/refactor/references/readability.md` (general). Items that look
removable but aren't are listed in `.claude/skills/refactor/references/load-bearing.md`.

## Authority & safety

- [regression] No node writes to a database. No `session.add/commit/flush/delete`, no `create_all`. Only the three granted tables are read (ADR-0004).
- [regression] ai-engine chooses no `Branch`, computes no trust score, and doesn't check auto-reply authority. Those are core-api's job (ADR-0001, ADR-0002).
- [regression] `llm_self_confidence` is only forwarded, never used (ADR-0003).
- [regression] Any retrieval threshold compares against the cross-encoder score, never an RRF score. `Candidate` has no score field (ADR-0005).
- [regression] Only masked ticket text (`subject_masked`, `body_masked`) reaches a provider or prompt.
- [regression] Nothing in a prompt grants authority, such as permission to auto-reply or to skip review.
- [regression] Nothing from `load-bearing.md` was simplified away.

## Failure paths

- [regression] Every new dependency failure ends at HITL. Either it raises (500 → `ai_engine_unavailable`) or it sets `degraded_reason` to an existing `ReasonCode` value.
- [regression] No infrastructure failure turns into an empty or "clean" result (`[]`, a zero vector, checks marked passed).
- [regression] `emit_signals` still can't raise. Any new lookup in it is inside a `try` and denies by default.
- [regression] No retries, no provider fallback, no graph cycle.
- [convention] Each broad `except` has a `# noqa: BLE001 — <why>` comment and returns the *safe* value.

## Node contract

- [regression] `__call__` never assigns to `self`.
- [regression] `__call__` returns only keys this node owns, and they are all `TriageState` fields.
- [convention] A branching node has a module-level `<Name>Outcome(StrEnum)`, `Outcome = <Name>Outcome`, and `decide() -> <Name>Outcome` (the module enum, not a bare `Outcome`).
- [convention] Outcome values carry business meaning in PascalCase, not True/False.
- [convention] `__init__` exists only for setup that should fail at boot. There is no dependency injection.
- [convention] The module ends with the production instance, named after the node's `name`.

## State

- [regression] Defaults read as "not run", and a check's default reads as "failed".
- [convention] New fields sit under the `# <NodeClassName>` header of their writer, in graph order.
- [convention] No reducer unless several nodes truly accumulate into the field.
- [convention] Any new value type lives in `core/` and is frozen.

## Wiring (`graph/triage.py`)

- [regression] Every outcome is routed and the graph compiles on import.
- [regression] Every path still ends at `emit_signals`, then the builder's end. The graph stays acyclic.
- [convention] Routes that carry a safety property have an inline comment.
- [convention] `tests/test_build.py` literal node and edge sets are updated. `test_safety_critical_routes` is extended if the change calls for it.

## Providers

- [regression] An unknown provider value raises at import, with no fallback.
- [regression] Construction opens no socket.
- [regression] The real implementation validates the reply and raises on anything malformed.
- [convention] Consumers import the singleton by name (`db`, `embedder`, `reranker`) or use `models.chat`. Each consumer module is listed in its `use_*` fixture.
- [convention] There is an offline deterministic variant, and a Fake plus `fake_*`, `use_*` and `reload_*` fixtures in conftest.

## Config

- [regression] ai-engine doesn't read `thresholds.yaml`. Per-request calibration comes from state.
- [convention] New tunables are `Settings` fields with a why-comment, read where they're used.
- [convention] Safety fallbacks, model/schema properties and lexicons are constants with a comment, not settings.
- [convention] If there are new env vars, they're in `infra/.env.example` and compose.

## Contracts (if touched)

- [regression] New persisted fields have defaults.
- [regression] TS types are regenerated, and `generated.ts` is not hand-edited.
- [regression] A new failure reason is a `ReasonCode` member, and core-api `apps/tickets/utils/pipeline.py` maps it.

## Tests

- [regression] Every new failure path has a test asserting where it ends up (raise, `degraded_reason`, or deny).
- [convention] The test file has a module docstring saying what it protects. Tests have behaviour-sentence names and docstrings for the failure mode.
- [convention] Tests use plain fakes and assert on recorded calls, with no `unittest.mock`, no `from conftest import`, and no `tests/__init__.py`.
- [convention] Tunables are changed with `monkeypatch.setattr(settings, …)`.
- [convention] Important invariants have had a mutation check.

## Style (see readability.md)

- [convention] Module docstring (what, spec § or ADR, the non-obvious invariant), then `from __future__ import annotations`, then imports in two groups: stdlib and third-party, then `ai_engine`.
- [convention] Comments say why and name silent failures. They don't restate code or explain pyright.
- [convention] Guard clauses, keyword-only parameters where there are several, no single-use wrappers.
- [convention] pyright is clean. Suppressions are per line, name the rule, and sit only at library boundaries. ruff check and format are clean.

## Verification & docs

- [regression] `uv run pytest services/ai-engine/tests -q`, `uvx pyright@1.1.414` and ruff all pass. If the wire schema or core-api changed, the whole-workspace `uv run pytest` passes too.
- [regression] Prompt or retrieval changes have live eval results with the deltas explained. No floor was lowered.
- [convention] `docs/graph-node-architecture.md` and `docs/architecture.md` reflect new topology or behaviour. `status.md` and `TODO.md` are updated together.
- [convention] Commits are small `type(scope): summary`, and each body says why.
