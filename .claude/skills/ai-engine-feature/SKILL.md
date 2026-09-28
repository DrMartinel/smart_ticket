---
name: ai-engine-feature
description: Workflow for building or changing anything in services/ai-engine, the FastAPI + LangGraph triage pipeline. Covers new graph nodes, providers (embedder, reranker, LLM client), TriageState fields, trust signals or failure reasons that reach core-api, retrieval (BM25, vector, RRF fusion, rerank), prompt version bumps, and new settings. It classifies the change, reads the matching exemplars, and produces a plan in a fixed shape. It then waits for approval before implementing with the repo's node contract, degrade-to-HITL failure semantics and fakes-based tests, and verifies with pytest, pyright and ruff. Use it for any implementation work under services/ai-engine/src, including small edits, and whenever the user says "add a node", "add a step to the graph", "new signal", "new provider", "change the prompt", "tweak retrieval", or describes a feature for the triage pipeline.
argument-hint: <what to build>
---

# ai-engine feature workflow

Feature: **$ARGUMENTS**. If that's empty, ask what to build before doing anything else.

ai-engine **proposes and never decides**. It reads the KB, runs the model, and sends
core-api a proposal plus trust signals. Every failure has to end with a human looking
at the ticket, under a reason code the dashboard can count. The conventions below
exist to keep that true as nodes, prompts and models change. Most bugs they prevent
don't fail loudly, so follow the recipe even for changes that look small.

Precedence: `CLAUDE.md` hard rules first, then the code as it stands now, then these
references, then `docs/`. If a doc disagrees with the code, the code wins, and fixing
the doc is part of the change.

## Reference files (read as needed)

| File | Read it when |
|---|---|
| `references/ai-engine-conventions.md` | Always, once per session. It covers the node contract, providers, config, failure semantics, DB and state |
| `references/recipes/node.md` | Adding or changing a graph node |
| `references/recipes/provider.md` | Adding or changing an embedder, reranker, LLM client or model server |
| `references/recipes/signal.md` | Anything core-api has to see: a TrustSignals field, a response field, or a new `ReasonCode` |
| `references/recipes/prompt.md` | Changing prompt text or the prompt version |
| `references/recipes/retrieval.md` | Touching BM25, vector search, fusion or rerank. The ADR-0005 check is mandatory |
| `references/testing.md` | Writing tests. It covers the conftest toolkit and templates |
| `references/checklist.md` | Self-review before handing back |
| `.claude/skills/refactor/references/readability.md` | General Python style: module shape, comments, naming, typing, commits |

---

## Phase 1: Classify

Decide which recipes apply. A change usually needs more than one:

- A new node almost always adds **state** fields (node.md step 1).
- If core-api has to act on the result, add **signal.md**.
- A node that calls a new external service adds **provider.md**.
- A new tunable number goes in `Settings` (see *Config* in ai-engine-conventions.md).

If you can't tell which recipe applies, ask. Don't guess.

## Phase 2: Read the exemplars

Before designing anything, open the live code the recipe points to. The skill
describes patterns, and the code shows the current version of them. At a minimum:

- `services/ai-engine/src/ai_engine/graph/nodes/rerank.py`: branching node
- `services/ai-engine/src/ai_engine/graph/nodes/retrieve.py`: single-exit node that uses providers
- `services/ai-engine/src/ai_engine/graph/nodes/emit_signals.py`: best-effort, deny-by-default
- `services/ai-engine/src/ai_engine/graph/triage.py`: the route list at the bottom
- `services/ai-engine/src/ai_engine/core/state.py` and `services/ai-engine/tests/conftest.py`

Look for existing helpers you can reuse before writing new ones.

## Phase 3: Plan, then STOP

Present the plan in this exact shape:

```markdown
## Plan: <feature>

**Recipes:** <node + signal + …>

**Files**
- <path>: <what changes>

**State** (field → owning node → default and what the default means)
- `x: bool = False` → XNode → "not run / failed"

**Outcomes & routes** (branching nodes only)
- XNode.<OUTCOME_A> → <target> (<why; safety property if any>)

**Failure paths** (every dependency the change touches)
- <dependency> raises → <raise → 500 → ai_engine_unavailable | degraded_reason="<ReasonCode value>" | deny-by-default> → HITL

**Tests** (failure paths first)
- test_<…>: <failure mode it prevents>

**Hard rules / ADRs in play**
- <e.g. ADR-0005 check applies; no new thresholds.yaml keys; contract field needs a default>

**Open questions**
- <anything that is the user's call>
```

**Wait for the user's approval.** The plan is where design mistakes are cheapest to
fix. Once code exists, a wrong failure shape or a misplaced route costs far more to
reverse.

## Phase 4: Implement

Follow the recipe steps in order, using the conventions files for style. Write each
test **alongside** the code it covers, and write the failure-path tests first. Keep
the change to what the plan listed. If you find something that should change outside
the plan, mention it instead of doing it.

## Phase 5: Verify

```bash
uv run pytest services/ai-engine/tests -q
uvx pyright@1.1.414
uvx ruff@0.16.7 check . --exclude .venv
uvx ruff@0.16.7 format --check . --exclude .venv
```

Then add whichever of these apply:

- The topology changed: print the graph and check the new edges.
  ```bash
  uv run --package ai-engine python -c \
    "from ai_engine.graph.build import triage_graph; print(triage_graph.get_graph().draw_mermaid())"
  ```
- `packages/contracts` or core-api changed: also run the whole workspace with `uv run pytest`.
- A prompt or retrieval change: run `uv run pytest evals/suites -q` against a live
  stack. Live suites **skip** when ai-engine is down, so a skip is not a pass. Say
  which it was.
- **Mutation check:** for each new safety test, break the invariant, confirm the
  test fails, then revert.

Report the results as they actually came out. If something fails, show the output.

## Phase 6: Self-review

Go through `references/checklist.md`. Fix every **[regression]** item. Fix every
**[convention]** item too, or say why you left it.

## Phase 7: Docs & commits

- Update the docs that describe what changed. For a node or route that means
  `docs/graph-node-architecture.md` (§4.3) and `docs/architecture.md`. If you touch
  `docs/status.md`, update `docs/TODO.md` along with it.
- Propose commits as small, single-concern `type(scope): summary`, for example
  `feat(ai-engine): …`, `test(ai-engine): …`, `feat(contracts): …`, `feat(prompts): …`.
  The body says why. A commit that relaxes a guardrail says so explicitly.
- **Don't commit unless the user asks.**
- Suggest running `/ai-engine-review` before opening the PR.
