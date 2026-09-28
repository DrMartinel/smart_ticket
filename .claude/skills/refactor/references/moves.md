# Refactor moves

The moves this repo has already made and endorsed. Each entry: the **smell** that
suggests it, the **move**, the **guard** (when *not* to), and the commit that set the
precedent — `git show <sha>` to see it done.

Before proposing any move, check `load-bearing.md`. A match there wins over a match here.

---

### 1. Inline a single-use wrapper — e6d55c9

- **Smell:** a function with one caller that wraps one call or one expression.
- **Move:** inline it at the call site.
- **Guard:** keep it if its *name* documents an invariant, if it isolates a boundary
  (I/O, an untyped library), or if a test targets it directly.

### 2. Delete unreachable code — 3c14839

- **Smell:** a check that can never fire because an earlier line already guarantees it.
- **Move:** delete it. The commit body *proves* unreachability and names the guard that
  still holds.
- **Guard:** "never fires in tests" is not proof. Trace every caller.

### 3. Remove speculative machinery — 6870c98, 922843c

- **Smell:** retry loops, breakers, budgets, pluggable providers, config flags — built
  for a need that hasn't materialised and making failure behaviour harder to state.
- **Move:** remove it end to end (code, settings, contracts, docs, tests).
- **Guard:** this usually **changes behaviour** or relaxes a spec requirement → it
  needs the user's explicit sign-off, and the commit says
  `Deliberately relaxes spec §X`. Update the ADR it touches. Keep any `ReasonCode`
  member it produced — persisted rows still deserialize it (`CIRCUIT_OPEN` is the
  worked example in `router.py`).

### 4. Replace DI plumbing with module singletons — 55e853b

- **Smell:** dependencies passed through constructors only so tests can swap them;
  an assembly function that just threads objects around.
- **Move:** the dependency becomes a module-level singleton built at import; the
  consumer imports it; tests swap it with a `monkeypatch`-based fixture that patches
  every module that reads it (`use_db`, `use_embedder`… in
  `services/ai-engine/tests/conftest.py`).
- **Guard:** construction must open no socket (import must stay safe with no DB).
  Consumers that need patching through a module attribute (e.g. `models.chat`) must
  keep accessing it that way.

### 5. Collapse scattered wiring into one place — 55e853b

- **Smell:** the shape of a system (routes, registrations, handlers) spread across
  several files, so no single place shows the whole.
- **Move:** one list, one file, top to bottom (`graph/triage.py`'s route list).
- **Guard:** if it stops fitting on a screen, split by sub-pipeline — don't push it back
  into the parts.

### 6. Group by owner — 9ac1f46

- **Smell:** fields or functions ordered by accident, or grouped under a misleading header.
- **Move:** group under a comment naming who writes/owns them, in flow order
  (`TriageState` fields under `# InferNode`, `# ValidateNode`, …).
- **Guard:** none — pure readability, no behaviour change.

### 7. Nested type → module level for type correctness — 27e7ce3

- **Smell:** a nested class overriding a base-class attribute of a different type, with
  pyright complaining about incompatible overrides.
- **Move:** define it at module level and assign it (`Outcome = RerankOutcome`).
- **Guard:** update every reference that named the nested path.

### 8. Unify a name across services — 3714f2d

- **Smell:** one concept spelled two ways in two services (`VLLM_CHAT_MODEL` vs `CHAT_MODEL`).
- **Move:** rename to the better name everywhere.
- **Guard:** env var renames reach `infra/.env.example`, `infra/docker-compose.yml`,
  docs and any deployed env — list them all in the proposal.

### 9. Fail at boot instead of falling back — b5e2176

- **Smell:** `try: X() except: Y()` or `.get(name, default_impl)` when selecting an
  implementation from config.
- **Move:** `match settings.x: case "a": … case other: raise ValueError(…)` at import.
- **Guard:** this turns a silent misconfiguration into a boot failure — intended, but
  say so in the commit and check CI envs set the value.

### 10. Drop comments that restate code — f78e11f, a1426ae

- **Smell:** comments that say what the next line does, or explain the type checker.
- **Move:** delete them.
- **Guard:** never delete a comment that explains *why* or names a silent failure —
  those are the load-bearing ones. If unsure, keep it.

### 11. Extract a pure decision from an I/O function — the `router.py` pattern

- **Smell:** a function that fetches, decides and writes, so its decision logic can only
  be tested with a DB (likely candidate: `services/core-api/apps/tickets/utils/pipeline.py`).
- **Move:** fetch first, pass the data into a pure function that returns the decision,
  then act on it. Test the pure function with no I/O.
- **Guard:** do **not** move a `Branch` choice anywhere except `router.py` (CLAUDE.md
  rule 1). Preserve transaction boundaries and idempotency behaviour exactly.

### 12. Use the contract enum member instead of its string literal

- **Smell:** `degraded_reason="embedding_unavailable"` (`pipeline.py`),
  `"all_llm_down"` (`graph/nodes/infer.py`) where a `ReasonCode` member exists.
- **Move:** `ReasonCode.EMBEDDING_UNAVAILABLE.value`, etc. A typo then fails at import
  instead of producing a reason the dashboard can't see.
- **Guard:** tests that pin the exact string must still pass unchanged. A literal that
  matches **no** enum member (e.g. `"mass_incident_short_circuit"`) is a *finding*, not a
  mechanical swap — changing it alters persisted values, so raise it with the user.

### 13. Type for strict pyright — f04445f, 894f950

- **Smell:** `reportUnknown*` noise, untyped Django attributes, `Any` leaking from a boundary.
- **Move:** declare runtime-added attributes on the model (`id: int`, `<fk>_id: int`,
  `RelatedManager[...]`), give FKs to string targets their model, type JSON-shaped
  fields. Suppress only at a genuinely untyped library boundary, one line, rule named.
- **Guard:** a type change that changes runtime behaviour is not a typing refactor.

---

## Adding a move

When a refactor sets a new precedent, add it here: smell, move, guard, commit sha.
Keep entries short; the commit is the long form.
