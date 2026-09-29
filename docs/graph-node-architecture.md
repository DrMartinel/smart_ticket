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
single conversion function** (`GraphBuilder.compile` in `core/build/builder.py`) and
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

**A node owns exactly four things.** Its name (auto-derived), its `__call__`
(the work), its `decide()` (which business outcome it reached), and its
`Outcome` enum. Nothing else. It uses the provider singletons (`db`,
`embedder`, `reranker`, `models.chat`) directly; an `__init__` is only for
one-time setup that must fail at boot, like `InferNode` loading its prompt.

**Outcomes carry business meaning, not booleans.** `InjectionDetected` /
`InjectionClear`, `EvidenceBelowFloor` / `EvidenceAboveFloor` — not `True` /
`False`. A reviewer can follow the flow without reading node internals.

**A node never knows what comes after it.** Successors are declared on a
`GraphBuilder`, which maps each outcome of a node *instance* to the next
instance, all in one route list in `graph/triage.py`. That makes nodes reusable
and removes any definition-order constraint between node classes. (A cycle could
be expressed, but `compile()` rejects it: every node runs at most once.)

**Everything is validated at startup.** Bad routes raise as they are declared;
unrouted outcomes and unreachable nodes raise inside `GraphBuilder.compile()` —
which `main.py` calls at uvicorn import time — never when the first ticket
takes an unusual branch.

**A node instance is a singleton and must stay stateless per call.** It is
built once, at import, at the bottom of its module; `BaseNode.__new__` raises
`TypeError` on a second construction of the same class, so tests import that
instance too. `__call__` runs per request and must never write to `self`:
`analyze` is a sync `def`, so FastAPI shares one instance across its
threadpool. All per-call data belongs in state.

---

## 4. The architecture

`ai_engine/core/` is everything the nodes are built on: `config.py`
(settings), `state.py`, `node.py` (`BaseNode`, `Terminal`), `providers/`
(`embeddings.py` and `reranker.py`, each holding its seam as an ABC, the real
and offline implementations, and the singleton selected at import; and
`llm/models.py`, the `LLMClient` seam and the chat/embed/rerank clients), `prompts/` (the
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
no defaults), so no path can silently leave a check at its default.

List-valued fields (`candidates`, `reranked`, `fewshots`) deliberately have
**no reducer**. Each is owned by exactly one node. Add a reducer
(`Annotated[list, operator.add]`) only for a field several nodes genuinely
accumulate into.

### 4.2 BaseNode — `core/node.py`

```python
class SingleExit(StrEnum):
    DONE = "Done"


class BaseNode(ABC):
    name: ClassVar[str]
    Outcome: ClassVar[type[StrEnum]] = SingleExit

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        stem = re.sub(r"Node$", "", cls.__name__)  # HybridRetrieveNode
        name = re.sub(r"(?<!^)(?=[A-Z])", "_", stem).lower()  # -> "hybrid_retrieve"
        if not name:
            raise TypeError("a node class cannot be named exactly 'Node'")
        cls.name = name
        if cls.Outcome is not SingleExit and cls.decide is BaseNode.decide:
            raise TypeError("... defines its own Outcome but does not override decide()")

    @classmethod
    def produces(cls, outcome: StrEnum) -> bool:
        return any(outcome is member for member in cls.Outcome)  # identity, see §4.4

    @abstractmethod
    def __call__(self, state: TriageState) -> dict: ...

    def decide(self, state: TriageState) -> StrEnum:
        return SingleExit.DONE
```

A node with more than one exit defines its enum at module level and assigns
it (`Outcome = RerankOutcome`) rather than nesting a `class Outcome`. An enum
with members cannot be subclassed, so a nested override is an unrelated class
that type checkers report as an incompatible override.

`Outcome` is a `StrEnum`: members compare and hash exactly like their string
values, so LangGraph's path-map lookup works either way, and `str(member)` is
the value — edge labels in `draw_mermaid()` read `EvidenceBelowFloor`, not
`Outcome.EVIDENCE_BELOW_FLOOR`.

`node.py` also defines `Terminal`, the node every path ends on:

```python
class Terminal(BaseNode):
    def __call__(self, state: TriageState) -> StateUpdate:
        return {}


terminal = Terminal()
```

Like every node it has one instance, `terminal`, and app code reaches it as
`builder.end`: every `GraphBuilder` shares it, and a path finishes by routing
to it: `g.route(emit_signals, SingleExit.DONE, g.end)`. Sharing is safe
because routes live on each builder. The builder recognises it by identity,
so a graph cannot gain a second end, and a `Terminal` subclass is just an
ordinary node that ends nothing.

It is a real node — registered as `terminal`, visible in traces and
`draw_mermaid()` — so every route targets a node instance and the builder
needs no marker special case in `route()`. It changes no state: returning a key
outside `TriageState` (such as `END`) would make LangGraph reject the update
and abort the run. It keeps LangGraph's `END` out of app code, because
`compile()` gives it the graph's only edge to `END`.

### 4.3 Wiring — `graph/triage.py`

The entire topology, as routes on the production node instances (safety
comments trimmed here):

```python
_triage = GraphBuilder(entry=injection)
_triage.route(injection, InjectionOutcome.INJECTION_DETECTED, emit_signals)
_triage.route(injection, InjectionOutcome.INJECTION_CLEAR, hybrid_retrieve)
_triage.route(hybrid_retrieve, SingleExit.DONE, rerank)
_triage.route(rerank, RerankOutcome.EVIDENCE_BELOW_FLOOR, emit_signals)  # refuse-before-LLM
_triage.route(rerank, RerankOutcome.EVIDENCE_ABOVE_FLOOR, select_fewshots)
_triage.route(select_fewshots, SingleExit.DONE, infer)
_triage.route(infer, SingleExit.DONE, validate)
_triage.route(validate, SingleExit.DONE, emit_signals)  # no cycle: schema failure goes to HITL
_triage.route(emit_signals, SingleExit.DONE, _triage.end)  # every path ends here

triage_graph = _triage.compile(TriageState)
```

`main.py` only imports and invokes `triage_graph`.

### 4.4 Builder — `core/build/`

`GraphBuilder(entry=node)` is generic — it knows nothing about triage — and
its `compile(state_schema)` is the only place a node
becomes a string. Routes are stored on the builder's `Graph`, keyed by node
**instance**, never on node classes or `Outcome` members (§7 says why).

The `core/build/` package — generic, it knows nothing about triage — splits the work three ways, none of it but the
builder importing LangGraph:

| Module | Object | Job |
|---|---|---|
| `edge.py` | `Edge(source, outcome, target)` | One route; valid on its own |
| `graph.py` | `Graph` | Holds the edges; finds the reachable nodes and proves the wiring sound |
| `builder.py` | `GraphBuilder` | `route()` adds an `Edge`; `compile()` asks the `Graph` for the validated nodes, then only translates them to LangGraph |

Nodes stay plain `BaseNode` instances; there is no separate node wrapper.

`route(source, outcome, target)` raises immediately on:

- an outcome the source's class cannot produce (`BaseNode.produces`, checked
  when the `Edge` is built) — by **identity**, because `Outcome` is a `StrEnum`
  and a member of another enum with the same value compares equal;
- an outcome that is already routed (`Graph.add`);
- a route out of `builder.end`, whose only exit is `END` (`Graph.add`).

A node *class* passed where an instance belongs is not checked at runtime:
pyright (in CI) rejects it at the call site.

`compile()` calls `Graph.validate()`, which finds the nodes by walking routes
from the entry, then, before anything is registered, raises `ValueError` on:

- two reachable node classes with the same name (LangGraph would collide);
- `builder.end` not reachable from the entry (with every outcome routed, every run
  would cycle until LangGraph's recursion limit aborts it);
- a reachable node with an unrouted outcome — including a target whose own
  routes were never declared;
- a node that has routes but is unreachable from the entry — which is what a
  route aimed at the wrong target leaves behind;
- a cycle, even one with a way out to the end (via stdlib
  `graphlib.TopologicalSorter`). Every node runs at most once per ticket, so a
  proposal that fails validation reaches a human rather than the model again.

Each instance registers under its own class's `name`, so a test double shows
up under its own name: a `FakeInferNode(...)` (a subclass of `InferNode`)
routed in a test graph appears as `fake_infer`.

Registration: each node is added through an adapter that raises `ValueError`
if its update has a key the state schema lacks — LangGraph would drop it
silently. (A non-dict update is rejected by LangGraph itself, with
`InvalidUpdateError`.) Single-outcome nodes get
`add_edge`, multi-outcome nodes get
`add_conditional_edges(name, instance.decide, {outcome: target_name})`,
`builder.end` gets `add_edge(name, END)`, and the entry is
`add_edge(START, entry.name)`.

Tests pin routes on the compiled graph (`triage_graph.get_graph().edges`, see
`tests/test_build.py`); the builder exposes no route mapping of its own.
`Graph.edges_from(node)` returns a tuple, so edges change only through `route()`.

### 4.5 Assembly — `triage_graph` in `graph/triage.py`

Each node module ends with its production instance. Nodes take no
dependencies: they use the provider singletons built at the bottom of the
provider modules (`db`, `embedder`, `reranker`, `models.chat`) directly.

```python
# nodes/rerank.py
rerank = RerankNode()
```

`graph/triage.py` imports those seven instances and routes them (§4.3). Each
instance is named after its node's `name`, so the variable, the
LangGraph node and the trace entry all read the same.

Every `Settings` value is read by the
code that consumes it — `bm25_search` reads `settings.bm25_top_k`,
`RerankNode` reads `settings.rerank_top_n` — so no tunable is threaded
through the assembly or a node that merely passes it on. Tests that need a
non-default value `monkeypatch.setattr(settings, ...)`.

Tests that exercise a node swap its providers for the fakes in
`tests/conftest.py` with the `use_db`, `use_embedder`, `use_reranker` and
`use_llm` fixtures, which patch every node module that reads that provider:
`use_db(fake_db()); emit_signals(state)` — the module's instance, never a
fresh `EmitSignalsNode()`, which raises. Tests that exercise the builder wire a small graph of
their own (`tests/test_compiler.py`). The production topology is pinned
literally by `tests/test_build.py`.

---

## 5. Writing a node

A branching node (`nodes/rerank.py`, abridged):

```python
class RerankOutcome(StrEnum):
    EVIDENCE_ABOVE_FLOOR = "EvidenceAboveFloor"
    EVIDENCE_BELOW_FLOOR = "EvidenceBelowFloor"


class RerankNode(BaseNode):
    Outcome = RerankOutcome

    def __call__(self, state: TriageState) -> StateUpdate:
        ...
        scores = reranker.score(query, [c.content for c in candidates])  # the module singleton
        ...
        return {"reranked": ranked[: settings.rerank_top_n]}

    def decide(self, state: TriageState) -> RerankOutcome:
        reranked = state.reranked
        if not reranked or reranked[0].score < state.retrieval_floor:
            return RerankOutcome.EVIDENCE_BELOW_FLOOR
        return RerankOutcome.EVIDENCE_ABOVE_FLOOR
```

A single-exit node needs neither an `Outcome` nor a `decide()` — it inherits
`SingleExit` and is routed with `SingleExit.DONE` (`HybridRetrieveNode`,
`InferNode`, `ValidateNode`, …).

Checklist when adding one (the full recipe is
`.claude/skills/ai-engine-feature/references/recipes/node.md`):

- If it branches, define a module-level `<Name>Outcome` enum in domain language,
  assign it to `Outcome`, and annotate `decide()` with it.
- Use the provider singletons directly, and add the module to the matching
  `use_*` fixture in `tests/conftest.py`.
- Keep `__call__` free of writes to `self`; return only changed keys.
- End the module with its production instance, named after the node's `name`.
- Route every outcome in `graph/triage.py`.
- Add it to the literal node and edge sets in `tests/test_build.py`, and test
  `decide()` directly there.

---

## 6. Execution order (important)

`decide()` runs **after** `__call__`'s update is merged, so the routing
decision always sees fresh state. Worked example, a ticket whose LLM answer
fails the schema:

```
input:             {"ticket": ..., "retrieval_floor": 0.45, ...}
after injection:   {..., "injection_detected": False, ...}
decide()        -> InjectionClear      -> HybridRetrieveNode
after retrieve:    {..., "candidates": [...10]}
after rerank:      {..., "reranked": [top1.score=0.81, ...]}
decide()        -> EvidenceAboveFloor  -> SelectFewshotsNode -> InferNode
after infer:       {..., "proposal": None}                       # unparseable JSON
after validate:    {..., "schema_valid": False, ...}
                   -> EmitSignalsNode -> Terminal -> END          # no retry: to HITL
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
`SingleExit.DONE` is one member shared by every single-exit node, so
their successors overwrite each other; a class could never serve two graphs;
and every compile — each test's included — would rewire the production nodes.

**A class-keyed flow table (`FLOW: dict[type[BaseNode], dict[Outcome, type]]`).**
The previous design. Reads like a whiteboard, but being keyed by class it
needed a separate node list matched back to classes with `isinstance`, and a
class could appear only once in the whole table. Replaced by `GraphBuilder`,
which routes instances directly.

**Choosing the successor while a ticket runs (`Command(goto=...)`).** No
startup validation, and refuse-before-LLM would rest on
whatever `decide()` returns rather than on the graph's structure.

---

## 8. Accepted tradeoff

Routing is no longer local to the node. Reading `RerankNode` does not tell
you where `EvidenceBelowFloor` goes — you look it up at the bottom of
`graph/triage.py`. We accept this: the route list fits on one screen, it is what you would draw on a
whiteboard anyway, and it is what makes whole-graph validation possible. If it
ever grows past comfortable reading, split it into one wiring function per
sub-pipeline (routes are per instance, so a class can appear in several)
rather than pushing wiring back into the nodes.

---

## 9. Gotchas

**Do not name a node class exactly `Node`** — `BaseNode.__init_subclass__`
raises `TypeError`. It also raises `TypeError` for a class that sets its own
`Outcome` without overriding `decide()` (the default returns
`SingleExit.DONE`, which such a class cannot produce) — at class definition,
before the class is wired into any graph.

**Renaming a node class renames the node.** Today that is safe — there is no
checkpointer, so no persisted run refers to a node name — but traces, streamed
step names and `get_graph()` output change. If a checkpointer is ever added,
in-flight threads saved under the old name will not resume: drain or migrate
before renaming.

**Annotate `decide()` with the module-level enum** (`-> RerankOutcome`, not
`-> Outcome`). LangGraph calls `get_type_hints()` on the router, which
resolves annotations against module globals where a bare `Outcome` does not
exist. Getting it wrong fails in `GraphBuilder.compile()` at startup, not at
runtime.

**List-valued state fields replace rather than append** unless the schema
declares a reducer — which is what we want today (§4.1).

**Fan-out.** A router may return a list of node names to run several nodes in
parallel. Not used; if added, the compiler's target conversion must handle
sequences.

---

## 10. Verifying the topology

Assert it rather than eyeballing it:

- `tests/test_build.py::test_compiled_edges_are_exactly_the_triage_topology` —
  pins the production graph's edge set literally.
- `tests/test_build.py::test_safety_critical_routes` — pins
  refuse-before-LLM to its route and asserts there is no `validate → infer` cycle.
- `tests/test_compiler.py` — every validation rule in §4.4 raises.

To look at it:

```bash
uv run --package ai-engine python -c \
  "from ai_engine.graph.build import triage_graph; print(triage_graph.get_graph().draw_mermaid())"
```
