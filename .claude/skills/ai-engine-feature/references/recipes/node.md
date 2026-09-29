# Recipe: add a graph node

Open these before writing: `graph/nodes/rerank.py` (branching), `graph/nodes/retrieve.py`
(single-exit, providers), `graph/triage.py` (the route list at the bottom),
`core/state.py`, `tests/conftest.py`, `tests/test_build.py`.

## 1. State fields: `core/state.py`

Add the node's outputs under a new `# <Name>Node` comment, placed in **graph order**
among the existing groups.

```python
    # DuplicateScreenNode
    duplicate_detected: bool = False
    duplicate_matched_phrases: list[str] = []
```

- The default means "this node has not run". For a check, it means **failed**.
- No reducer on lists.
- If a field holds a new value type, define that type in `core/`, as a frozen
  pydantic model.

## 2. The node module: `graph/nodes/<module>.py`

Branching skeleton:

```python
"""
<What this node does> — spec §<x>. <The one non-obvious invariant, e.g. why it runs
before retrieval, or what a wrong answer here costs downstream.>
"""

from __future__ import annotations

from enum import StrEnum

from ai_engine.core.node import BaseNode, StateUpdate
from ai_engine.core.state import TriageState


class <Name>Outcome(StrEnum):
    <BUSINESS_MEANING_A> = "<BusinessMeaningA>"
    <BUSINESS_MEANING_B> = "<BusinessMeaningB>"


class <Name>Node(BaseNode):
    """<One line on its role. For a branching node, say where the interesting
    outcome goes and why.>"""

    Outcome = <Name>Outcome

    def __call__(self, state: TriageState) -> StateUpdate:
        ...
        return {"<field>": value}  # only the keys this node owns

    def decide(self, state: TriageState) -> <Name>Outcome:  # module enum, not `Outcome`
        if <condition on fresh state>:
            return <Name>Outcome.<BUSINESS_MEANING_A>
        return <Name>Outcome.<BUSINESS_MEANING_B>


<name> = <Name>Node()
```

Single-exit: leave out the enum, `Outcome = …` and `decide()`.

Checks while writing:

- `__call__` never assigns to `self`.
- Use `settings.x` where it's needed, and read `retrieval_floor` from `state`.
- Choose a failure shape from `ai-engine-conventions.md` → *Failure semantics* on
  purpose. Put a comment on any `except`.
- Build any text sent to a provider from `ticket.subject_masked` and
  `ticket.body_masked` only.

## 3. Providers → `tests/conftest.py`

If the node reads `db`, `embedder` or `reranker`, import the singleton by name and
**add the new module to the tuple in the matching `use_*` fixture**. If it calls the
chat LLM, go through `models.chat`. `use_llm` already patches that.

## 4. Wiring: `graph/triage.py`

- Import the instance, and its `Outcome` enum if it has one.
- Route **every** outcome. An unrouted outcome raises in `compile()` at import.
- If a route encodes a safety property, give it an inline comment, as in
  `# refuse-before-LLM`.
- Keep the graph acyclic, and keep every path ending at `emit_signals`, then
  `_triage.end`.
- An early-exit branch, such as a guard that finds something, goes **straight to
  `emit_signals`** and skips the remaining cost. See how `injection` does it.
- Check the result:
  ```bash
  uv run --package ai-engine python -c \
    "from ai_engine.graph.build import triage_graph; print(triage_graph.get_graph().draw_mermaid())"
  ```

## 5. Tests

- `tests/test_<module>.py`, from the template in `../testing.md`. Write the
  failure-path tests first.
- `tests/test_build.py`:
  - a `decide()` test per outcome;
  - add the node name to **both** literal node sets;
  - add its edges to the literal edge set;
  - add an assertion in `test_safety_critical_routes` if a route carries a guarantee.

## 6. Does core-api need to see it?

If the result has to reach `TrustSignals`, `AIRunResponse` or routing, continue with
`signal.md`. A state field on its own is invisible outside ai-engine.

## 7. Docs

`docs/graph-node-architecture.md` §4.3 lists the routes, so update it. Update the
stage walk-through in `docs/architecture.md` too.

## Done when

- [ ] The state fields are grouped under the node, with safe defaults.
- [ ] Every outcome is routed and the graph compiles on import.
- [ ] The `use_*` fixture includes the new module, if the node reads a provider.
- [ ] Failure-path tests exist and pass the mutation check.
- [ ] The literal sets in `test_build.py` are updated.
- [ ] pytest, mypy and ruff are all clean.
