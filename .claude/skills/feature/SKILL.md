---
name: feature
description: Workflow for building or changing a feature anywhere in this repo - core-api (Django + Ninja routes, models, services, tunables, settings), ai-engine (graph nodes, providers, TriageState fields, trust signals and failure reasons that reach core-api, retrieval, prompt version bumps) and the two web apps. It picks the services the change touches, reads the matching recipes and exemplars, and produces a plan in a fixed shape. It then waits for approval before implementing with the repo's degrade-to-HITL failure semantics, layer rules and failure-path-first tests, and verifies with each service's checks. Use it for any implementation work under services/, including small edits, and whenever the user says "add a route", "add a node", "new model", "new signal", "new provider", "new setting", "change the prompt", "tweak retrieval", or describes a feature to build.
argument-hint: <what to build>
---

# Feature workflow

Feature: **$ARGUMENTS**. If that's empty, ask what to build before doing anything else.

**The LLM proposes, deterministic code decides.** ai-engine reads the KB, runs the
model and sends core-api a proposal plus trust signals; core-api makes every
decision and every write; the web apps show what core-api returns. Every failure
has to end with a human looking at the ticket, under a reason code the dashboard
can count. The references below exist to keep that true as code, prompts and
models change. Most bugs they prevent don't fail loudly, so follow the recipe even
for changes that look small.

Precedence: `CLAUDE.md` hard rules first, then the code as it stands now, then these
references, then `docs/`. If a doc disagrees with the code, the code wins, and fixing
the doc is part of the change.

## Reference files (read as needed)

| File | Read it when |
|---|---|
| `references/ai-engine/conventions.md` | ai-engine is touched. Once per session. It covers the node contract, providers, config, failure semantics, DB and state |
| `references/ai-engine/recipes/node.md` | Adding or changing a graph node |
| `references/ai-engine/recipes/provider.md` | Adding or changing an embedder, reranker, LLM client or model server |
| `references/ai-engine/recipes/signal.md` | Anything core-api has to see: a TrustSignals field, a response field, or a new `ReasonCode` |
| `references/ai-engine/recipes/prompt.md` | Changing prompt text or the prompt version |
| `references/ai-engine/recipes/retrieval.md` | Touching BM25, vector search, fusion or rerank. The ADR-0005 check is mandatory |
| `references/ai-engine/testing.md` | Writing ai-engine tests. It covers the conftest toolkit and templates |
| `references/core-api/recipes/route.md` | Adding or changing a core-api route |
| `references/core-api/recipes/model.md` | Adding or changing a model, a column, or raw SQL |
| `references/core-api/recipes/setting.md` | A new tunable number or operational setting, in either service |
| `.claude/skills/refactor/references/where-logic-goes.md` | core-api is touched: which layer each piece goes in |
| `references/<service>/checklist.md` | Self-review before handing back, one per service touched (`ai-engine`, `core-api`, `web`) |
| `.claude/skills/refactor/references/readability.md` | General Python style: module shape, comments, naming, typing, commits |

---

## Phase 1: Classify

Decide which services the change touches, then which recipes apply. A change
usually needs more than one:

- **ai-engine:** a new node almost always adds **state** fields (node.md step 1).
  A node that calls a new external service adds **provider.md**.
- **Across the wire:** if core-api has to act on an ai-engine result, add
  **signal.md**, which changes both services in the same PR (hard rule 4).
- **core-api:** a new endpoint is **route.md**; new data is **model.md**; the work
  itself goes where `where-logic-goes.md` puts it.
- **A new number** is **setting.md**: `thresholds.yaml` if it shapes a decision,
  `.env.example` if it is wiring.
- **web:** a page that calls a new or changed route reads `references/web/checklist.md`.

If you can't tell which recipe applies, ask. Don't guess.

## Phase 2: Read the exemplars

Before designing anything, open the live code the recipe points to. The skill
describes patterns, and the code shows the current version of them.

**ai-engine**, at a minimum:

- `services/ai-engine/src/ai_engine/graph/nodes/classify_category/node.py`: branching node
- `services/ai-engine/src/ai_engine/graph/nodes/retrieve/node.py`: single-exit node that uses providers
- `services/ai-engine/src/ai_engine/graph/nodes/emit_signals/node.py`: terminal, reads only the state, "not run" reads as failed
- `services/ai-engine/src/ai_engine/graph/triage.py`: the route list at the bottom
- `services/ai-engine/src/ai_engine/graph/state.py`, `graph/ticket.py`, `graph/nodes/infer/proposals.py`, `graph/nodes/emit_signals/signals.py`, `services/ai-engine/src/ai_engine/schemas.py` and `services/ai-engine/tests/conftest.py`

**core-api**: the app the change belongs in (CLAUDE.md's *Layout* table names
each one), its `views.py`, `models.py` and service in `utils/`, and its `tests/`.
For a decision, `apps/tickets/utils/router.py` and `pipeline.py`; for access,
`apps/accounts/permissions.py` and `utils/catalog.py`.

**web**: the nearest existing page in the same area, and `lib/api.ts`.

Look for existing helpers you can reuse before writing new ones.

## Phase 3: Plan, then STOP

Present the plan in this exact shape. Leave out a section that doesn't apply.

```markdown
## Plan: <feature>

**Services and recipes:** <core-api: route + model · ai-engine: node + signal · web>

**Files**
- <path>: <what changes>

**State** (ai-engine; field → owning node → default and what the default means)
- `x: bool = False` → XNode → "not run / failed"

**Outcomes & routes** (ai-engine branching nodes only)
- XNode.<OUTCOME_A> → <target> (<why; safety property if any>)

**Routes** (core-api; method path → permission → agent tier → service call)
- `POST /api/<path>` → `Permission.<X>` → `AgentTier.<tier>` → `<service>.<action>`

**Data** (core-api; table, columns and their defaults, migration, raw SQL)

**Failure paths** (every dependency or refusal the change touches)
- <dependency> raises → <500 → ai_engine_unavailable | degraded_reason="<ReasonCode>" | HITL `<ReasonCode>` | 4xx `<refusal code>`>

**Tests** (failure paths first)
- test_<…>: <failure mode it prevents>

**Hard rules / ADRs in play**
- <e.g. ADR-0005 check applies; new thresholds.yaml key, version bumped; wire field needs a default; make types>

**Open questions**
- <anything that is the user's call>
```

**Wait for the user's approval.** The plan is where design mistakes are cheapest to
fix. Once code exists, a wrong failure shape, a misplaced route or a decision in the
wrong service costs far more to reverse.

## Phase 4: Implement

Follow the recipe steps in order. Write each test **alongside** the code it covers,
and write the failure-path tests first. Keep the change to what the plan listed. If
you find something that should change outside the plan, mention it instead of doing
it.

## Phase 5: Verify

Run the checks for each service touched (CLAUDE.md's *Commands*):

| Touched | Run |
|---|---|
| ai-engine | `uv run pytest services/ai-engine/tests -q` · `uv run mypy` |
| core-api | `cd services/core-api && make check` · `make coverage` if `masking.py` or `router.py` changed · `manage.py makemigrations --check` if a model changed · `make types` if a schema changed |
| web | that app's `npm run lint` and `npm run build` |
| always | `uvx ruff@0.16.7 check . --exclude .venv` · `uvx ruff@0.16.7 format --check . --exclude .venv` |

Then add whichever of these apply:

- The graph topology changed: print the graph and check the new edges.
  ```bash
  uv run --package ai-engine python -c \
    "from ai_engine.graph.build import triage_graph; print(triage_graph.get_graph().draw_mermaid())"
  ```
- The wire schema changed, or both services did: run the whole workspace with `uv run pytest`.
- A prompt or retrieval change needs `uv run pytest evals/suites -q` against a live
  stack. **Don't start it unless the user asks**; say it is needed. Live suites
  **skip** when ai-engine is down, so a skip is not a pass.
- **Mutation check:** for each new safety test, break the invariant, confirm the
  test fails, then revert.

Report the results as they actually came out. If something fails, show the output.

## Phase 6: Self-review

Go through `references/<service>/checklist.md` for each service touched. Fix every
**[regression]** item. Fix every **[convention]** item too, or say why you left it.

## Phase 7: Docs & commits

- Update the docs that describe what changed. For an ai-engine node or route that
  means `docs/graph-node-architecture.md` (§4.3) and `docs/architecture.md`. If you
  touch `docs/status.md`, update `docs/TODO.md` along with it.
- Propose commits as small, single-concern `type(scope): summary`, for example
  `feat(ai-engine): …`, `feat(teams): …`, `test(core-api): …`, `feat(prompts): …`.
  The body says why. A commit that relaxes a guardrail says so explicitly.
- **Don't commit unless the user asks.**
- Suggest running `/review` before opening the PR.
