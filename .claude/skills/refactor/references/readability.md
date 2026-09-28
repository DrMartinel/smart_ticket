# Readability & maintainability conventions

The repo-wide taste guide for Python in `services/ai-engine`, `services/core-api`
and `evals`. `services/ai-engine` is the reference standard —
it was refactored to this style first; when a rule is unclear, open the cited
exemplar and copy what it does.

These sit **under** the hard rules in `CLAUDE.md`. Where the two meet, CLAUDE.md wins.

## Contents

1. Module shape · 2. Comments · 3. Docstrings · 4. Naming · 5. Code shape ·
6. Simplicity · 7. Types · 8. Errors · 9. Config · 10. Purity ·
11. Per-service shape · 12. Tests · 13. Commits

---

## 1. Module shape

Every module reads top-down in the same order:

1. **Module docstring.** What this module is, the spec section / ADR it implements,
   and the *one* invariant a reader would not guess from the code. Not a table of
   contents.
   - `services/core-api/infrastructure/ai_engine.py` — who calls it, and that a
     transport failure must be treated as fail-open-to-human.
   - `services/core-api/apps/tickets/utils/router.py` — the only module allowed to
     choose a `Branch`, and why the gate order is load-bearing.
   - `services/ai-engine/src/ai_engine/graph/nodes/rerank.py` — where refuse-before-LLM
     is decided, and which score thresholds may compare against.
2. `from __future__ import annotations`
3. **Imports in three groups**, blank line between:
   stdlib + third-party → `contracts.*` → first-party (`apps.*` or `ai_engine.*`).
   See `services/ai-engine/src/ai_engine/graph/nodes/infer.py`,
   `services/core-api/apps/tickets/utils/pipeline.py`.
4. Module constants, then private helpers (`_name`), then the public class/functions.
5. Import-time wiring (a singleton, a provider selected from settings) at the
   **bottom**, under a `# --- <what> ---` divider with a comment saying why it is
   fatal at boot. See `services/ai-engine/src/ai_engine/core/providers/reranker.py`.

## 2. Comments

A comment earns its place by saying **why**, and especially by naming what would break
**silently** if someone "cleaned it up". That is the failure mode this codebase fears
most: things that stay green while being wrong.

Good (from the code):

```python
# `connect()` MUST stay inside the try: a DB outage here has to
# produce deny-by-default, not a 500 out of the terminal node
# that every path through the graph passes through.
```

```python
# Order by the raw distance, not by `score`: `<=>` in ORDER BY is what
# the HNSW index (vector_cosine_ops) can serve; `1 - <=>` is not.
```

- Cite the ADR or spec section when one exists (`ADR-0005`, `spec §6.3`). It lets the
  next reader find the argument instead of re-litigating it.
- Don't restate the code. Don't write comments whose job is to explain the type
  checker (commit f78e11f removed exactly those).
- History ("this used to…") belongs in the commit message — unless it explains why the
  current code must *stay* this way (`infer.py`'s `kb_slug` comment is the legitimate
  kind: it says what goes wrong without it).
- Inline comments on a line that encodes a guarantee are welcome:
  `_triage.route(rerank, RerankOutcome.EVIDENCE_BELOW_FLOOR, emit_signals)  # refuse-before-LLM`.

## 3. Docstrings

State the **contract**, including what happens on failure — that is what a caller
needs and cannot see from the signature.

- `Embedder.embed` (`core/providers/embeddings.py`): "Raises on provider failure —
  never a zero or empty vector", and *why* (it would read as "KB has nothing relevant"
  instead of "embedder down", which reach HITL under different reason codes).
- `AIEngineUnavailable` (`core-api/infrastructure/ai_engine.py`): "Callers MUST treat this as
  fail-open-to-human … never as skip the AI step and auto-approve."
- A class that is shared across threads says so and what that forbids
  (`BaseNode`: "`__call__` must never write to `self`").

One line is fine when there is no contract beyond the name.

## 4. Naming

- **Domain language, not mechanism.** Outcomes read `EvidenceBelowFloor`,
  `InjectionDetected` — never `True`/`False`, never `Branch2`.
- **Enums over strings and booleans** for anything that routes or gets counted.
  `StrEnum`, UPPER_SNAKE members, values that carry meaning.
- **One concept, one name, across services** (commit 3714f2d dropped the `VLLM_`
  prefix in core-api so its settings match ai-engine's `CHAT_MODEL`, `EMBED_MODEL`, …).
- `_private` for module-internal helpers and constants. Safety constants are private
  on purpose (`_POLICY_FALLBACK_DENY`) — they are not knobs.
- Test names are sentences describing behaviour:
  `test_embedder_failure_propagates_rather_than_returning_empty_candidates`.

## 5. Code shape

- **Guard clauses and early returns** over nested `if`/`else`
  (`ValidateNode.__call__`, `RerankNode.decide`).
- **Keyword-only parameters** once there are several, or when two are easy to swap:
  `_checks(*, schema_valid, …)` in `validate.py`, `_block(reason_code, *, detail="")`
  in `router.py`, `LLMClient.__init__(self, *, model, api_key, …)`.
- **No defaults where every caller must decide.** `validate.py`'s `_checks` has none,
  so no code path can silently leave a check at its default.
- **Flat over nested; small but not fragmented.** A helper that has one caller and
  wraps one call gets inlined (commit e6d55c9). A helper that names an idea used in
  several places, or isolates a boundary, stays.
- **One concept lives in one place.** The whole triage topology is one route list at
  `graph/triage.py` (commit 55e853b deleted `flow.py`). `TriageState`
  fields are grouped under the node that writes them (commit 9ac1f46).

## 6. Simplicity

The direction of travel in this repo is **subtraction**. Retry, circuit breaker,
per-ticket budget, cloud providers, a mixin, a flow table — all removed
(6870c98, 922843c). Each removal made the failure behaviour *easier to state*.

- Delete before adding. Add no machinery for a need that doesn't exist yet.
- Prefer a module-level singleton plus test patching over dependency-injection plumbing
  (55e853b). Construction must stay socket-free so import stays safe.
- Extract a seam (an ABC) only when there are two real implementations or a test fake
  needs one (`Embedder`, `Reranker`). One implementation and no fake → no ABC.
- **But** indirection that protects an invariant is not complexity — see
  `load-bearing.md`. Read the comment before simplifying.

## 7. Types

- Pyright **strict** for source, **standard** for tests (root `pyproject.toml`).
  `uvx pyright@1.1.414` must be clean.
- Modern syntax: PEP 695 `type StateUpdate = dict[str, Any]`, generic methods
  `def compile[S: StateLike](…)`, `X | None`, `StrEnum`.
- Value objects are frozen pydantic models: `model_config = ConfigDict(frozen=True)`
  (`RankedChunk`, `LexicalHit`, `LLMResult`).
- Suppressions: one line, **name the rule**, only at an untyped library boundary:
  `# pyright: ignore[reportUnknownMemberType]` (see `core/build/builder.py`).
- Django: declare what Django adds at runtime (`id: int`, `ticket_id: int`,
  reverse managers) — see the pyright row in CLAUDE.md's Gotchas.

## 8. Errors

- **Fail at boot, not on the first unlucky request.** Build at import; parse config
  into a model at startup; select providers with
  `match … case other: raise ValueError(f"unknown x: {other!r} (expected …)")`.
- **No silent fallback.** Falling back to another provider/calibration looks healthy
  and is wrong (`reranker.py`'s selection comment).
- **Degrade toward humans with a specific `ReasonCode`.** Never toward "assume fine".
  Free-text reasons are invisible to the dashboard, which is built on the enum.
- **One exception type per failure class**, with a docstring saying how callers must
  treat it (`AllLLMDownError`, `AIEngineUnavailable`). Re-raise with `from e`.
- A broad `except Exception` only for best-effort work that must not fail the caller,
  and it says so: `except Exception:  # noqa: BLE001 — best-effort only, …`
  (`emit_signals.py`). The fallback value it returns must be the *safe* one.

## 9. Config

- **No magic numbers.** Decision/routing numbers → `services/core-api/config/thresholds.yaml`.
  Operational tunables (top-k, timeouts, batch sizes) → the service's settings
  (`services/ai-engine/src/ai_engine/core/config.py`, `core-api/config/settings/`),
  each with a comment on what it trades off.
- Read a setting **where it is used**; don't thread it through constructors.
- Some numbers are deliberately **not** config, and say so in a comment:
  - safety invariants (`_POLICY_FALLBACK_DENY` — "a safety invariant wearing a
    magic-number costume");
  - properties of a model or schema (`EMBED_DIM` — changing it needs a migration);
  - linguistic lexicons (`NEGATIONS` in `validate.py`, PII regexes in `patterns.py`).

## 10. Purity

Decisions are pure functions: inputs in, decision out, no I/O, no global config.
Fetch everything **before** the call and pass it in. `router.py` is the model — it is
why every branch is testable without a DB and why decisions can be replayed against
`routing_decisions.thresholds_used`. When an I/O-heavy function also *decides*
something, splitting the decision out is usually the best refactor available.

## 11. Per-service shape

| Service | Shape | Notes |
|---|---|---|
| ai-engine | `core/` (settings, state, node base, providers, retrieval, db, prompts) · `graph/` (build + nodes) · `main.py` | `core/` never imports `graph/`. No writes, ever (ADR-0004). Details: `.claude/skills/ai-engine-feature/references/ai-engine-conventions.md` |
| core-api | `apps/<app>/{views.py, request_schema.py, response_schema.py, models.py, utils.py or utils/, tasks.py, tests/}` · `common/` · `infrastructure/` · `config/settings/{base,development,production,test}.py` | `views.py` is thin (bind, validate, call a model method, manager method or util). Request bodies go in `request_schema.py`; every handler declares `response=` with an output Schema from `response_schema.py` (aliases for renamed fields, `resolve_<field>` for computed ones) and returns models, never hand-built dicts. `common/` holds only what several apps share. Fat models: a write, decision or query that belongs to one entity is a method on it or its manager (`article.set_auto_reply_allowed`, `Ticket.objects.submit`, `ReviewItem.objects.for_queue`); logic that is no single model's behaviour goes in `utils` (pure decisions, text processing, the pipeline, cross-model aggregations like the metrics dashboard). `tasks.py` is only Celery entry points, because task names are module paths. `infrastructure/` is transport to other processes, never judgement. `router.py` is the only `Branch` chooser. `db_table` names mirror `infra/migrations/sql/`. |
| contracts | `services/core-api/contracts/*.py`, `services/ai-engine/src/ai_engine/contracts/*.py` | One copy per service; wire types identical in both (parity suite). New persisted fields get a default. Regenerate TS after any change; never hand-edit `generated.ts`. |
| evals | `evals/suites`, `evals/golden`, `evals/baselines` | Never lower a floor, average per-category F1, or drop a category. |

## 12. Tests

- One `test_<module>.py` per module, opening with a docstring that says what the file
  protects and why failure there matters.
- Each non-trivial test has a docstring naming the **failure mode** it prevents, with
  enough context to judge a future change as regression vs. intentional shift.
- **Failure paths first.** For every dependency: what if it raises, times out, returns
  junk, returns empty? Most of this system's correctness is what it does then.
- Plain fake classes that record calls — not `unittest.mock`. A fake you can read in
  one place beats a Mock configured three lines from the assertion.
- Pin the **invariant**, not the implementation
  (`test_llm_self_confidence_does_not_change_score` survives any scorer rewrite).
- **Mutation check** the important ones: break the invariant on purpose, watch the
  test fail, revert.
- When a test surprises you, check the test.

## 13. Commits

Small, one concern each, `type(scope): summary` — e.g.
`refactor(ai-engine): inline extract_error_codes into bm25_search`,
`feat(ai-engine): …`, `test(ai-engine): …`, `docs: …`, `ci: …`.

The body says **why**, and for a removal, **what still holds afterwards**:

```
refactor(kb): remove unreachable approver check in set_auto_reply_allowed

actor.is_manager is dereferenced two lines earlier, so a None actor has
already raised before this check runs; the manager check is the guard.
Enabling auto-reply still requires a manager actor, a non-empty reason,
and writes the KbAuthorityLog row (ADR-0002).
```

When a change relaxes a guardrail or spec requirement, say so in so many words:
`Deliberately relaxes spec §10.2's per-ticket budget.` Docs that describe the changed
behaviour are updated in the **same** commit.
