# LangGraph Node Architecture — Design Record

Status: implemented
Scope: how nodes, state and wiring are structured in ai-engine's triage graph
(`services/ai-engine/src/ai_engine/graph/`)
Audience: anyone (human or assistant) picking this codebase up cold

---

## 1. The problem this solves

Stock LangGraph identifies nodes and edges by **string names**:

```python
graph.add_node("rerank", rerank_fn)
graph.add_conditional_edges("rerank", router, ["emit_signals", "select_shots"])
```

That works, but in a codebase it means: typos are only caught when an unlucky
ticket takes that branch at runtime, renaming a node is a grep-and-pray
exercise, routing conditions are anonymous booleans with no business meaning,
and nothing validates that every branch a node can produce actually has
somewhere to go.

Strings exist in LangGraph for a real reason — when a checkpointer is used,
node identity is persisted and has to survive a process restart:

```
{"thread_id": "ticket-4471", "next": ["rerank"], "channel_values": {...}}
```

A class object cannot round-trip through a database row; a name can. So the
goal is not to remove strings from LangGraph. It is to **push them into a
single conversion function** (`compile_graph` in `graph/build.py`) and keep
application code referencing classes and typed enums.

---

## 2. Core concepts (LangGraph vocabulary)

**State** — the shared schema that flows through the whole graph:
`TriageState` in `graph/state.py`. Nodes receive the full state and return only
the keys they changed; LangGraph merges the update.

**Node** — a callable taking the state and returning a dict of updates. We use
class instances with `__call__`.

**Edge** — the link deciding which node runs next. A plain edge is
unconditional; a conditional edge calls a router that returns a key, which is
mapped to the next node's name.

**Checkpointer** — an optional storage backend (Postgres, SQLite, memory) that
saves state after every node so a run can resume after a crash, pause for
human approval (`interrupt_before`), or be replayed. **ai-engine does not use
one**: `main.py` compiles the graph with `checkpointer=None`, every
`POST /v1/analyze` runs start to finish in memory, and retry/idempotency lives
at core-api's Celery layer. The practical consequence is in §9.

---

## 3. Design principles

**A node owns exactly five things.** Its name (auto-derived), its `__init__`
(dependencies only), its `__call__` (the work), its `decide()` (which business
outcome it reached), and its `Outcome` enum. Nothing else.

**Outcomes carry business meaning, not booleans.** `InjectionDetected` /
`InjectionClear`, `EvidenceBelowFloor` / `EvidenceAboveFloor` — not `True` /
`False`. A reviewer can follow the flow without reading node internals.

**A node never knows what comes after it.** Successors live in one flow table.
That makes nodes reusable, makes cycles expressible, and removes any
definition-order constraint between node classes.

**Everything is validated at startup.** Unrouted outcomes, dangling targets and
unreachable nodes all raise inside `compile_graph()` — which `main.py` calls
at uvicorn import time — never when the first ticket takes an unusual branch.

**A node instance is a singleton and must stay stateless per call.** `__init__`
runs once and may hold read-only collaborators (DB pool, embedder, LLM client)
and config. `__call__` runs per request and must never write to `self`:
`analyze` is a sync `def`, so FastAPI shares one instance across its
threadpool. All per-call data belongs in state.

---

## 4. The architecture

### 4.1 State — `graph/state.py`

One `TypedDict`, `TriageState`. Nodes return partial updates.

List-valued fields (`candidates`, `reranked`, `fewshots`) deliberately have
**no reducer**. Each is owned by exactly one node, and the `validate → infer`
retry must overwrite the previous attempt, not append to it. Add a reducer
(`Annotated[list, operator.add]`) only for a field several nodes genuinely
accumulate into.

### 4.2 BaseNode — `graph/base.py`

```python
class Terminal:
    """Edge target meaning 'stop here'. Keeps LangGraph's END out of app code."""


class BaseNode(ABC):
    name: ClassVar[str]

    class Outcome(StrEnum):
        DONE = "Done"

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        stem = re.sub(r"Node$", "", cls.__name__)  # HybridRetrieveNode
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", stem).lower()  # -> "hybrid_retrieve"
        if not name:
            raise TypeError("a node class cannot be named exactly 'Node'")
        cls.name = name

    @abstractmethod
    def __call__(self, state: TriageState) -> dict: ...

    def decide(self, state: TriageState) -> BaseNode.Outcome:
        return self.Outcome.DONE
```

`Outcome` is a `StrEnum`: members compare and hash exactly like their string
values, so LangGraph's path-map lookup works either way, and `str(member)` is
the value — edge labels in `draw_mermaid()` read `EvidenceBelowFloor`, not
`Outcome.EVIDENCE_BELOW_FLOOR`.

`base.py` also defines the flow table's types —
`Target = type[BaseNode] | type[Terminal]` and
`Flow = dict[type[BaseNode], dict[Enum, Target]]` — so `flow.py` depends only on
`base.py` and the nodes, never on the builder.

### 4.3 Flow table — `graph/flow.py`

The entire topology in one place (safety comments trimmed here):

```python
FLOW: Flow = {
    InjectionNode: {
        InjectionNode.Outcome.INJECTION_DETECTED: EmitSignalsNode,
        InjectionNode.Outcome.INJECTION_CLEAR: HybridRetrieveNode,
    },
    HybridRetrieveNode: {HybridRetrieveNode.Outcome.DONE: RerankNode},
    RerankNode: {
        RerankNode.Outcome.EVIDENCE_BELOW_FLOOR: EmitSignalsNode,  # refuse-before-LLM
        RerankNode.Outcome.EVIDENCE_ABOVE_FLOOR: SelectFewshotsNode,
    },
    SelectFewshotsNode: {SelectFewshotsNode.Outcome.DONE: InferNode},
    InferNode: {InferNode.Outcome.DONE: ValidateNode},
    ValidateNode: {
        ValidateNode.Outcome.RETRY_INFERENCE: InferNode,  # the only cycle
        ValidateNode.Outcome.SCHEMA_VALID: EmitSignalsNode,
        ValidateNode.Outcome.RETRIES_EXHAUSTED: EmitSignalsNode,
    },
    EmitSignalsNode: {EmitSignalsNode.Outcome.DONE: Terminal},
}

ENTRY = InjectionNode
```

### 4.4 Compiler — `graph/build.py`

`compile_graph(state_schema, nodes, flow, entry, checkpointer=None)` is
generic — it knows nothing about triage — and is the only place a class
becomes a string. Before registering anything it
checks, and raises `ValueError` on:

- an instance that matches no flow entry, or more than one;
- two instances for the same flow class;
- the entry class having no instance;
- a flow class having no instance;
- a class whose own `Outcome` has no `DONE` but which does not override
  `decide()` (it would crash on first call);
- a route keyed by an outcome the class cannot produce;
- an outcome with no route;
- a route to a class that has no instance;
- a node unreachable from the entry.

Instances are matched to flow classes with **`isinstance`, not `type()`**, and
registered under the *flow class's* name. That is the test seam: pass
`class FakeInferNode(InferNode)` in place of the real `InferNode` and it is
wired as `infer`.

Registration: single-outcome nodes get `add_edge`, multi-outcome nodes get
`add_conditional_edges(name, instance.decide, {outcome: target_name})`,
`Terminal` becomes `END`, and the entry is `add_edge(START, entry.name)`.

### 4.5 Assembly — `main.py`

`main.py` builds the providers and the seven node instances inline, at import
time, and compiles them once:

```python
_providers = build_providers(settings)
_graph = compile_graph(
    TriageState,
    [InjectionNode(), HybridRetrieveNode(db=_providers.db, ...), RerankNode(...),
     SelectFewshotsNode(...), InferNode(...), ValidateNode(...),
     EmitSignalsNode(db=_providers.db)],
    FLOW,
    ENTRY,
    checkpointer=None,
)
```

Tests build the same list wired to fakes with the `triage_nodes` fixture
(`tests/conftest.py`) and call `compile_graph` themselves.

---

## 5. Writing a node

A branching node (`nodes/rerank.py`, abridged):

```python
class RerankNode(BudgetedNode):
    class Outcome(StrEnum):
        EVIDENCE_ABOVE_FLOOR = "EvidenceAboveFloor"
        EVIDENCE_BELOW_FLOOR = "EvidenceBelowFloor"

    def __init__(self, *, reranker: Reranker, top_n: int) -> None:
        self._reranker = reranker  # read-only after construction
        self._top_n = top_n

    def __call__(self, state: TriageState) -> dict:  # budget checked first
        ...
        return {"reranked": ranked[: self._top_n]}

    def decide(self, state: TriageState) -> RerankNode.Outcome:
        reranked = state.get("reranked") or []
        if not reranked or reranked[0].score < state["retrieval_floor"]:
            return self.Outcome.EVIDENCE_BELOW_FLOOR
        return self.Outcome.EVIDENCE_ABOVE_FLOOR
```

A single-exit node needs neither an `Outcome` override nor a `decide()` — it
inherits `DONE` and gets a plain edge (`HybridRetrieveNode`, `InferNode`, …).

A node that spends tokens, latency or a network round-trip inherits
`BudgetedNode` (`graph/budget.py`) instead of `BaseNode`. The node still
writes an ordinary `__call__(self, state) -> dict`; when the class is defined,
`BudgetedNode.__init_subclass__` wraps that `__call__` so the per-request
budget is checked before it runs. `check_budget(state)` raises
`BudgetExceeded`; the wrapper catches it and returns only
`degraded_reason="budget_exceeded"`, so nodes write no degrade code at all.
Leaving the node's own keys absent is safe because every reader uses `.get()`
with an empty default — an over-budget ticket still routes below the floor to
`emit_signals`. Never let `BudgetExceeded` escape a node: it would abort
`graph.invoke` and turn a degrade-to-human into a 500. Because the wrap is
automatic, the check cannot be forgotten — a test fake that subclasses
`InferNode` and overrides `__call__` is wrapped too. Because the check is part
of the node, it runs on every pass through the `validate → infer` retry, not
once at graph entry.

Checklist when adding one: define `Outcome` members in domain language; put
dependencies in `__init__` and nothing else; pick `BudgetedNode` if the node
spends anything; keep `__call__` free of writes to `self`; return only
changed keys; add the class to `FLOW` with every outcome routed; add an
instance to the node list in `main.py` and to the `triage_nodes` fixture; test
`decide()` directly (see `tests/test_build.py`).

---

## 6. Execution order (important)

`decide()` runs **after** `__call__`'s update is merged, so the routing
decision always sees fresh state. Worked example, a ticket whose first LLM
answer fails the schema:

```
input:             {"ticket": ..., "iteration": 0, "retrieval_floor": 0.45, ...}
after injection:   {..., "injection": {"detected": False, ...}}
decide()        -> InjectionClear      -> HybridRetrieveNode
after retrieve:    {..., "candidates": [...10]}
after rerank:      {..., "reranked": [top1.score=0.81, ...]}
decide()        -> EvidenceAboveFloor  -> SelectFewshotsNode -> InferNode
after infer:       {..., "proposal": None}                       # unparseable JSON
after validate:    {..., "validation": {"schema_valid": False}, "iteration": 1}
decide()        -> RetryInference      -> InferNode              # loops back once
after infer:       {..., "proposal": <AutoReplyProposal>}
after validate:    {..., "validation": {"schema_valid": True, ...}}
decide()        -> SchemaValid         -> EmitSignalsNode -> END
```

---

## 7. Alternatives considered and rejected

**Plain functions registered with string names (stock LangGraph).** No rename
safety, no validation that branches are wired, routing carries no meaning.

**`yes()` / `no()` methods on a branching base class.** Only expresses two-way
branches; `ValidateNode` already needs three outcomes.

**Separate `LinearNode` / `BranchNode` base classes.** Two base classes for one
concept. A single-entry route map already yields a plain edge.

**Targets stored in the `Outcome` enum values (`INJECTION_CLEAR = HybridRetrieveNode`).**
Node classes would have to be defined sinks-first, the `validate → infer`
cycle would need `lambda` thunks, and a node would hardcode its successors.

**Calling the next node's `__call__` directly from inside a node.** Collapses
two graph steps into one: no per-step streaming or trace entry, no
`interrupt_before`, not in `draw_mermaid()`. Everything LangGraph provides is
per-step; bypassing the graph forfeits it.

**Edges passed to each node's `__init__`.** Scatters wiring across
construction sites so no single place knows the whole graph, and reachability
cannot be validated.

---

## 8. Accepted tradeoff

Routing is no longer local to the node. Reading `ValidateNode` does not tell
you where `RetryInference` goes — you look it up in `FLOW`. We accept this: the
table fits on one screen, it is what you would draw on a whiteboard anyway, and
it is what makes whole-graph validation possible. If it ever grows past
comfortable reading, split it per sub-pipeline rather than pushing wiring back
into the nodes.

---

## 9. Gotchas

**Do not name a node class exactly `Node`** — `BaseNode.__init_subclass__`
raises `TypeError`.

**Renaming a node class renames the node.** Today that is safe — there is no
checkpointer, so no persisted run refers to a node name — but traces, streamed
step names and `get_graph()` output change. If a checkpointer is ever added,
in-flight threads saved under the old name will not resume: drain or migrate
before renaming.

**Qualify `decide()`'s return annotation with the class**
(`-> RerankNode.Outcome`, not `-> Outcome`). LangGraph calls `get_type_hints()`
on the router, which resolves annotations against module globals where a bare
`Outcome` does not exist. Getting it wrong fails in `compile_graph()` at
startup, not at runtime.

**List-valued state fields replace rather than append** unless the schema
declares a reducer — which is what we want today (§4.1).

**Never fold `budget.py` into `build.py`** (or a shared `utils.py`). Nodes
import `BudgetedNode`, and `build.py` imports the nodes — a circular import.
`budget.py` imports only `base.py` and `state.py`, which keeps it safe.

**Fan-out.** A router may return a list of node names to run several nodes in
parallel. Not used; if added, the compiler's target conversion must handle
sequences.

---

## 10. Verifying the topology

Assert it rather than eyeballing it:

- `tests/test_build.py::test_compiled_edges_match_flow` — the compiled graph's
  edge set equals the set derived from `FLOW`.
- `tests/test_build.py::test_safety_critical_flow_rows` — pins
  refuse-before-LLM and the bounded retry to their FLOW rows.
- `tests/test_compiler.py` — every validation rule in §4.4 raises.

To look at it:

```bash
uv run --package ai-engine python -c \
  "from ai_engine.main import _graph; print(_graph.get_graph().draw_mermaid())"
```
