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
single conversion function** (`GraphBuilder.compile` in `graph/build.py`) and
keep application code referencing node instances and typed enums.

---

## 2. Core concepts (LangGraph vocabulary)

**State** — the shared schema that flows through the whole graph:
`TriageState` in `core/state.py`, a frozen pydantic model. Nodes receive a
`TriageState` instance and return a dict of only the fields they changed;
LangGraph merges the update.

**Node** — a callable taking the state and returning a dict of updates. We use
class instances with `__call__`.

**Edge** — the link deciding which node runs next. A plain edge is
unconditional; a conditional edge calls a router that returns a key, which is
mapped to the next node's name.

**Checkpointer** — an optional storage backend (Postgres, SQLite, memory) that
saves state after every node so a run can resume after a crash, pause for
human approval (`interrupt_before`), or be replayed. **ai-engine does not use
one**: `GraphBuilder.compile` passes no checkpointer, every
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

**A node never knows what comes after it.** Successors are declared on a
`GraphBuilder`, which maps each outcome of a node *instance* to the next
instance, all in one wiring function. That makes nodes reusable, makes cycles
expressible, and removes any definition-order constraint between node classes.

**Everything is validated at startup.** Bad routes raise as they are declared;
unrouted outcomes and unreachable nodes raise inside `GraphBuilder.compile()` —
which `main.py` calls at uvicorn import time — never when the first ticket
takes an unusual branch.

**A node instance is a singleton and must stay stateless per call.** `__init__`
runs once and may hold read-only collaborators (DB pool, embedder, LLM client)
and config. `__call__` runs per request and must never write to `self`:
`analyze` is a sync `def`, so FastAPI shares one instance across its
threadpool. All per-call data belongs in state.

---

## 4. The architecture

`ai_engine/core/` is everything the nodes are built on: `config.py`
(settings), `state.py`, `node.py` (`BaseNode`, `Terminal`), `budget.py`
(`BudgetedNode`), `providers/` (the embedding and reranking seams as ABCs in
`base.py`; the embedders, rerankers and `factory.py`; and `llm/`, the
`LLMClient` seam and its client, chat-model factories and circuit breaker), `prompts/` (the
versioned system prompts and their loader), `db/` (the SQLAlchemy client and
table declarations) and `retrieval/` (BM25, vector, RRF). Outside it are only
`graph/` (builder, wiring, nodes) and `main.py`. The graph imports from
`core`; `core` never imports from the graph.

### 4.1 State — `core/state.py`

One frozen pydantic model, `TriageState`, with every field flat — the injection
verdict is `injection_detected` / `injection_matched_patterns`, and each
validation check is its own field (`schema_valid`, `quote_match_ratio`, …).
Nodes read fields as attributes
(`state.reranked`) and return partial update dicts — returning a whole model
would overwrite every field. Progressive-output fields default to what "this
node has not run" reads as (`[]`, `None`, `0`).

What LangGraph (1.2.9) does with a pydantic schema, pinned in
`tests/test_state.py`:

- It validates the merged state when building the **next** node's input, so a
  wrong-typed update aborts the run one step later with a `ValidationError` — a
  500, which core-api routes to a human as `AIEngineUnavailable`.
- It silently **drops** an update key that is not a field (as it did with the
  `TypedDict`). `extra="forbid"` only guards direct construction, so
  `GraphBuilder` raises on such a key instead (§4.4).
- `graph.invoke` returns a plain dict; `main.py` re-validates it into a
  `TriageState`.
- It infers a node's input schema from the `state:` annotation on `__call__`
  unless told otherwise. `GraphBuilder.compile` passes
  `input_schema=state_schema` so the graph's schema always wins.

`candidates` is `list[Candidate]` and `reranked` is `list[RankedChunk]`. Both
types live in `core/retrieval/`, not in their nodes, because `core` never
imports from `graph/`.

The validation defaults read as "every check failed": refuse-before-LLM skips
the validator, and `emit_signals` must not report passing checks nobody ran.
`ValidateNode` writes every check on every path (through `_checks`, which has
no defaults), because a key left out would keep the previous attempt's value
on the `validate → infer` retry.

List-valued fields (`candidates`, `reranked`, `fewshots`) deliberately have
**no reducer**. Each is owned by exactly one node, and the `validate → infer`
retry must overwrite the previous attempt, not append to it. Add a reducer
(`Annotated[list, operator.add]`) only for a field several nodes genuinely
accumulate into.

### 4.2 BaseNode — `core/node.py`

```python
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

`node.py` also defines `Terminal`, the node every path ends on:

```python
class Terminal(BaseNode):
    class Outcome(StrEnum):
        DONE = "Done"

    def __call__(self, state: TriageState) -> dict:
        return {}
```

It is a real node — registered as `terminal`, visible in traces and
`draw_mermaid()` — so every route targets a node instance and the builder
needs no marker special case in `route()`. It changes no state: returning a key
outside `TriageState` (such as `END`) would make LangGraph reject the update
and abort the run. It keeps LangGraph's `END` out of app code, because
`compile()` gives it the graph's only edge to `END`.

### 4.3 Wiring — `graph/flow.py`

The entire topology in one function (safety comments trimmed here). Every node
is a required keyword, so a caller cannot forget one:

```python
def wire_triage(*, injection, retrieve, rerank, fewshots, infer, validate, emit) -> GraphBuilder:
    g = GraphBuilder(entry=injection)
    g.route(injection, InjectionNode.Outcome.INJECTION_DETECTED, emit)
    g.route(injection, InjectionNode.Outcome.INJECTION_CLEAR, retrieve)
    g.route(retrieve, HybridRetrieveNode.Outcome.DONE, rerank)
    g.route(rerank, RerankNode.Outcome.EVIDENCE_BELOW_FLOOR, emit)  # refuse-before-LLM
    g.route(rerank, RerankNode.Outcome.EVIDENCE_ABOVE_FLOOR, fewshots)
    g.route(fewshots, SelectFewshotsNode.Outcome.DONE, infer)
    g.route(infer, InferNode.Outcome.DONE, validate)
    g.route(validate, ValidateNode.Outcome.RETRY_INFERENCE, infer)  # the only cycle
    g.route(validate, ValidateNode.Outcome.SCHEMA_VALID, emit)
    g.route(validate, ValidateNode.Outcome.RETRIES_EXHAUSTED, emit)
    g.route(emit, EmitSignalsNode.Outcome.DONE, Terminal())  # no deps: built here
    return g
```

### 4.4 Builder — `graph/build.py`

`GraphBuilder(entry=node)` is generic — it knows nothing about triage — and
its `compile(state_schema)` is the only place a node
becomes a string. Routes are stored on the builder, keyed by node **instance**,
never on node classes or `Outcome` members (§7 says why).

`route(source, outcome, target)` raises immediately on:

- a node class passed where an instance is expected (`TypeError`);
- an outcome the source's class cannot produce — checked by **identity**,
  because `Outcome` is a `StrEnum` and a member of another enum with the same
  value compares equal;
- an outcome that is already routed;
- a route out of a `Terminal` (its only exit is `END`).

`compile()` finds the nodes by walking routes from the entry, then, before
registering anything, raises `ValueError` on:

- two reachable instances with the same node name (LangGraph would collide);
- no `Terminal` reachable from the entry (with every outcome routed, every run
  would cycle until LangGraph's recursion limit aborts it);
- a class whose own `Outcome` has no `DONE` but which does not override
  `decide()` (it would crash on first call);
- a reachable node with an unrouted outcome — including a target whose own
  routes were never declared;
- a node that has routes but is unreachable from the entry — which is what a
  route aimed at the wrong target leaves behind.

Each instance registers under its own class's `name`. That is the test seam:
pass a `FakeInferNode(...)` (a subclass of `InferNode`) as `infer=` and it is
wired where the real one would be, visible in the graph as `fake_infer`.

Registration: each node is added through an adapter that raises `ValueError`
if its update has a key the state schema lacks — LangGraph would drop it
silently — and `TypeError` if it is not a dict. Single-outcome nodes get
`add_edge`, multi-outcome nodes get
`add_conditional_edges(name, instance.decide, {outcome: target_name})`,
a `Terminal` gets `add_edge(name, END)`, and the entry is
`add_edge(START, entry.name)`.

`builder.entry` and `builder.routes` (a read-only mapping) let tests pin
individual routes without compiling.

### 4.5 Assembly — `main.py`

`main.py` builds the providers and the seven node instances inline, at import
time, and compiles them once:

```python
_providers = build_providers()
_graph = wire_triage(
    injection=InjectionNode(),
    retrieve=HybridRetrieveNode(db=_providers.db, embedder=_providers.embedder),
    rerank=RerankNode(reranker=_providers.reranker),
    fewshots=SelectFewshotsNode(db=_providers.db, embedder=_providers.embedder),
    infer=InferNode(llm=_providers.llm),
    validate=ValidateNode(),
    emit=EmitSignalsNode(db=_providers.db),
).compile(TriageState)
```

Constructors take collaborators only. Every `Settings` value is read by the
code that consumes it — `bm25_search` reads `settings.bm25_top_k`,
`RerankNode` reads `settings.rerank_top_n` — so no tunable is threaded
through `main.py` or a node that merely passes it on. Tests that need a
non-default value `monkeypatch.setattr(settings, ...)`.

Tests build the same instances wired to fakes with the `triage_nodes` fixture
(`tests/conftest.py`), which returns a dict keyed by `wire_triage`'s
parameters: `wire_triage(**triage_nodes()).compile(TriageState)`.

---

## 5. Writing a node

A branching node (`nodes/rerank.py`, abridged):

```python
class RerankNode(BudgetedNode):
    class Outcome(StrEnum):
        EVIDENCE_ABOVE_FLOOR = "EvidenceAboveFloor"
        EVIDENCE_BELOW_FLOOR = "EvidenceBelowFloor"

    def __init__(self, *, reranker: Reranker) -> None:
        self._reranker = reranker  # read-only after construction

    def __call__(self, state: TriageState) -> dict:  # budget checked first
        ...
        return {"reranked": ranked[: settings.rerank_top_n]}

    def decide(self, state: TriageState) -> RerankNode.Outcome:
        reranked = state.reranked
        if not reranked or reranked[0].score < state.retrieval_floor:
            return self.Outcome.EVIDENCE_BELOW_FLOOR
        return self.Outcome.EVIDENCE_ABOVE_FLOOR
```

A single-exit node needs neither an `Outcome` override nor a `decide()` — it
inherits `DONE` and gets a plain edge (`HybridRetrieveNode`, `InferNode`, …).

A node that spends tokens, latency or a network round-trip inherits
`BudgetedNode` (`core/budget.py`) instead of `BaseNode`. The node still
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
changed keys; add a parameter to `wire_triage` and route every outcome; pass
an instance in `main.py` and in the `triage_nodes` fixture; test `decide()`
directly (see `tests/test_build.py`).

---

## 6. Execution order (important)

`decide()` runs **after** `__call__`'s update is merged, so the routing
decision always sees fresh state. Worked example, a ticket whose first LLM
answer fails the schema:

```
input:             {"ticket": ..., "iteration": 0, "retrieval_floor": 0.45, ...}
after injection:   {..., "injection_detected": False, ...}
decide()        -> InjectionClear      -> HybridRetrieveNode
after retrieve:    {..., "candidates": [...10]}
after rerank:      {..., "reranked": [top1.score=0.81, ...]}
decide()        -> EvidenceAboveFloor  -> SelectFewshotsNode -> InferNode
after infer:       {..., "proposal": None}                       # unparseable JSON
after validate:    {..., "schema_valid": False, ..., "iteration": 1}
decide()        -> RetryInference      -> InferNode              # loops back once
after infer:       {..., "proposal": <AutoReplyProposal>}
after validate:    {..., "schema_valid": True, ...}
decide()        -> SchemaValid         -> EmitSignalsNode -> Terminal -> END
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

**Successors attached to `Outcome` members at startup
(`Outcome.INJECTION_CLEAR.next = retrieve`).** Avoids the definition-order and
thunk problems above, but writes wiring onto shared global objects:
`BaseNode.Outcome.DONE` is one member inherited by every single-exit node, so
their successors overwrite each other; a class could never serve two graphs;
and every compile — each test's included — would rewire the production nodes.

**A class-keyed flow table (`FLOW: dict[type[BaseNode], dict[Outcome, type]]`).**
The previous design. Reads like a whiteboard, but being keyed by class it
needed a separate node list matched back to classes with `isinstance`, and a
class could appear only once in the whole table. Replaced by `GraphBuilder`,
which routes instances directly.

**Choosing the successor while a ticket runs (`Command(goto=...)`).** No
startup validation, and refuse-before-LLM and the bounded retry would rest on
whatever `decide()` returns rather than on the graph's structure.

---

## 8. Accepted tradeoff

Routing is no longer local to the node. Reading `ValidateNode` does not tell
you where `RetryInference` goes — you look it up in `wire_triage`. We accept
this: the function fits on one screen, it is what you would draw on a
whiteboard anyway, and it is what makes whole-graph validation possible. If it
ever grows past comfortable reading, split it into one wiring function per
sub-pipeline (routes are per instance, so a class can appear in several)
rather than pushing wiring back into the nodes.

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
`Outcome` does not exist. Getting it wrong fails in `GraphBuilder.compile()`
at startup, not at runtime.

**List-valued state fields replace rather than append** unless the schema
declares a reducer — which is what we want today (§4.1).

**Never fold `budget.py` into `build.py`** (or a shared `utils.py`). Nodes
import `BudgetedNode`, and `build.py` imports the nodes — a circular import.
`budget.py` imports only `node.py` and `state.py`, which keeps it safe.

**Fan-out.** A router may return a list of node names to run several nodes in
parallel. Not used; if added, the compiler's target conversion must handle
sequences.

---

## 10. Verifying the topology

Assert it rather than eyeballing it:

- `tests/test_build.py::test_compiled_edges_match_wiring` — the production
  graph's edge set equals the set derived from `wire_triage`'s routes.
- `tests/test_build.py::test_safety_critical_routes` — pins
  refuse-before-LLM and the bounded retry to their routes.
- `tests/test_compiler.py` — every validation rule in §4.4 raises.

To look at it:

```bash
uv run --package ai-engine python -c \
  "from ai_engine.main import _graph; print(_graph.get_graph().draw_mermaid())"
```
