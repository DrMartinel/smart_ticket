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

1. **Module docstring.** One sentence saying what this module does (§3).
2. `from __future__ import annotations`
3. **Imports in three groups**, blank line between:
   stdlib → third-party → first-party (`apps.*`, `config.*`, `infrastructure.*` or `ai_engine.*`).
   See `services/ai-engine/src/ai_engine/graph/nodes/infer/node.py`,
   `services/core-api/apps/tickets/utils/pipeline.py`.
4. Module constants, then the public classes and functions, then any private
   helpers (`_name`), which are the last resort (§5).
5. Import-time wiring (a singleton, a provider selected from settings) at the
   **bottom**, under a `# --- <what> ---` divider. See
   `services/ai-engine/src/ai_engine/graph/nodes/candidate_pool/shortlister.py`.

## 2. Comments

A comment says **what** the code next to it does, in a plain sentence, when the
name and the code don't already say it. Never **why** it is that way, never
**how** it works.

```python
# The source this build writes.
SOURCE = "entity_graph"
```

- The why lives in the ADR (`docs/adr/`), the commit message, or
  `load-bearing.md`, and a test guards it. Cite the ADR or spec section
  (`ADR-0005`, `spec §6.3`) so a reader can find the argument.
- Don't restate the code. Don't write comments whose job is to explain the type
  checker (commit f78e11f removed exactly those).
- History ("this used to…") belongs in the commit message.
- Older code still has why-comments. Trim one when you touch its code, after
  checking its reason, especially a silent failure it names, is recorded in an
  ADR or `load-bearing.md`. Add the entry first if it isn't.

## 3. Docstrings

One plain sentence saying **what** the module, class or function does. Not its
inputs, outputs or exceptions (the signature and type hints have them), no why,
no how.

```python
def replace(self, rows: list[AssociationRow], snapshot: KbSnapshot) -> tuple[int, int]:
    """Replaces the `entity_graph` rows with `rows`."""
```

A test's docstring, if it has one, says what it checks:
`"""Checks that a sampled build writes nothing to the database."""`

## 4. Naming

- **Domain language, not mechanism.** Outcomes read `EvidenceBelowFloor`,
  `InjectionDetected` — never `True`/`False`, never `Branch2`.
- **Enums over strings and booleans** for anything that routes or gets counted.
  `StrEnum`, UPPER_SNAKE members, values that carry meaning.
- **One concept, one name, across services** (commit 3714f2d dropped the `VLLM_`
  prefix in core-api so its settings match ai-engine's `CHAT_MODEL`, `EMBED_MODEL`, …).
- `_private` for module-internal helpers and constants. Safety values are never
  knobs (the `(False, "high")` deny of `pipeline.trust_signals` when no KB page applies).
- Test names are sentences describing behaviour:
  `test_embedder_failure_propagates_rather_than_returning_empty_candidates`.

## 5. Code shape

- **Guard clauses and early returns** over nested `if`/`else`
  (`ValidateNode.__call__`, `ClassifyCategoryNode.decide`).
- **Keyword-only parameters** once there are several, or when two are easy to swap:
  `_block(reason_code, *, detail="")`
  in `router.py`, `ChatClient.__init__(self, *, model, chat_model, …)`.
- **No defaults where every caller must decide.** `router.py`'s `Router` takes its
  thresholds with none, so no call can route on a forgotten default (CLAUDE.md rule 1).
- **Extract by meaning, not by use count.** Extract a block that is a named
  business rule, has its own edge cases, or deserves its own test. Inline one of
  1–3 obvious lines whose name would restate them (commit e6d55c9). An extracted
  function that needs more than 3 arguments passed through is a wrong cut: move
  the boundary or inline it.
- **A private `_helper` is the last resort.** Before writing one, ask in order: one
  row → model method; which rows → queryset method; neither → a method on the class
  that owns the data or the work (in core-api, a service class in `utils`), named as
  a domain action. A module-level function only for generic work tied to no use case
  or model (building a regex, finding a pattern in a string: `normalize_ws`).
- **A class has to earn it.** It holds state or groups several behaviours around
  one thing. A class with one public method hasn't earned one: the method goes on the
  class that owns that data or work.
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
  needs one (`Embedder`, `Shortlister`). One implementation and no fake → no ABC.
- **But** indirection that protects an invariant is not complexity — see
  `load-bearing.md`. Check it, and the ADRs, before simplifying.

## 7. Types

- mypy with the django-stubs plugin everywhere (root `pyproject.toml`).
  `uv run mypy` must be clean.
- Modern syntax: PEP 695 `type` aliases, generic methods
  `def compile[S: StateLike](…)`, `X | None`, `StrEnum`.
- Value objects are frozen pydantic models: `model_config = ConfigDict(frozen=True)`
  (`RankedChunk`, `LexicalHit`, `LLMResult`).
- Suppressions: one line, **name the error code**, only at an untyped library boundary:
  `# type: ignore[misc]` (see `apps/core/testing.py`).
- Django: every model inherits `apps.core.models.BaseModel` for its UUID key (ADR-0011);
  don't declare what Django adds at runtime (managers, `<fk>_id`, reverse managers); the django-stubs plugin infers them.

## 8. Errors

- **Fail at boot, not on the first unlucky request.** Build at import; parse config
  into a model at startup; select providers with
  `match … case other: raise ValueError(f"unknown x: {other!r} (expected …)")`.
- **No silent fallback.** Falling back to another provider/calibration looks healthy
  and is wrong.
- **Degrade toward humans with a specific `ReasonCode`.** Never toward "assume fine".
  Free-text reasons are invisible to the dashboard, which is built on the enum.
- **One exception type per failure class**, with a docstring saying how callers must
  treat it (`AllLLMDownError`, `AIEngineUnavailable`). Re-raise with `from e`.
- A broad `except Exception` only for best-effort work that must not fail the caller,
  and it says so: `except Exception:  # noqa: BLE001 — best-effort only, …`
  (`emit_signals.py`). The fallback value it returns must be the *safe* one.

## 9. Config

- **No magic numbers.** Decision/routing numbers → `services/core-api/config/thresholds.yaml`.
  Operational tunables (top-k, timeouts, batch sizes) → the service's
  root `.env.example`,
  each with a comment on what it trades off; the settings code declares the type
  only, with no default.
- Read a setting **where it is used**; don't thread it through constructors.
- Some numbers are deliberately **not** config (their reasons are in
  `load-bearing.md` or the ADRs):
  - safety invariants (the `(False, "high")` deny of `pipeline.trust_signals`
    when no KB page applies);
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
| core-api | `apps/<app>/{views.py, request_schema.py, response_schema.py, models.py, utils.py or utils/, tasks.py, tests/}` · `apps/core` (shared foundation; imports no app) · `infrastructure/` · `config/settings/{base,development,production,test}.py` | Each piece goes in the layer that owns it (CLAUDE.md *Where logic goes*): `views.py` is HTTP only (take the request schema from `request_schema.py`, call a service class, model or queryset method, declare `response=` with a schema from `response_schema.py`, return models, never hand-built dicts); schemas check shape and fields, no database; model methods are rules about one row and stay pure-ish (no `request`, no writes to other models, no ai-engine/HTTP/Celery/email, no queries in a `@property`); queryset methods choose which rows; `utils` holds service classes (work across models, transactions, side effects, like the run in `pipeline.py`) and pure decisions (`router.py`, the only `Branch` chooser). `tasks.py` is only Celery entry points, because task names are module paths. The role gate is `apps/accounts/permissions.py`. `infrastructure/` is transport to other processes, never judgement. `db_table` names mirror `infra/migrations/sql/`. |
| wire schema | `services/core-api/infrastructure/dtos.py`; ai-engine `schemas.py` (HTTP bodies) with `graph/ticket.py`, `graph/nodes/infer/proposals.py`, `graph/nodes/emit_signals/signals.py` | Defined once per service, kept identical by hand (ADR-0010). New persisted fields get a default. Regenerate TS after any change; never hand-edit `generated.ts`. |
| evals | `evals/suites`, `evals/golden`, `evals/baselines` | Never lower a floor, average per-category F1, or drop a category. |

## 12. Tests

- One `test_<module>.py` per module, opening with a docstring that says what the file
  checks.
- Each test is **named for the failure mode** it prevents. A docstring, if any,
  says what it checks (§3); the why goes in the commit message or ADR.
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
