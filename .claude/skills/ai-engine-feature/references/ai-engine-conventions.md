# ai-engine conventions

Rules specific to `services/ai-engine`. For general Python style (module shape, comments,
naming, typing, errors, commits) see
`.claude/skills/refactor/references/readability.md`. It applies here too.

The design record behind the graph is `docs/graph-node-architecture.md`. If it
disagrees with the code, the code wins; fix the doc.

---

## Where things live

```
src/ai_engine/
  main.py          HTTP routes only. POST /v1/analyze: invoke the graph, shape the
                   response; POST /v1/embed, /v1/pii/detect: core-api's model calls (ADR-0012)
  schemas.py       the wire contract, mirrored in core-api's dtos.py (ADR-0010).
                   Imports nothing else from ai_engine
  core/            infrastructure. Never imports graph/, schemas.py or main.py
    config.py      Settings: types only; values in the repo root's .env.example
    providers/     the providers more than one caller shares:
                   embeddings.py (ABC + impls + import-time selection),
                   pii.py (Tier-2 PII NER, the only code that sees raw text),
                   clients.py (VLLMClient + JevClient on HttpClient, ChatClient + vllm_chat/openai_chat, and the chat/embed/rerank/ner/jev clients),
                   dtos.py (the request and reply shapes of the model servers)
    db/            client.py (the `db` singleton), tables.py (3 read-only tables, EMBED_DIM)
    prompts/       <name>.v<N>.md; __init__.py loads each at import (CLASSIFY_PROMPT, ...)
  graph/           the triage pipeline. Never imports main.py
    state.py       TriageState + the value types stored in it (Candidate, RankedChunk)
    build/         generic, triage-agnostic graph machinery:
      node.py      BaseNode, SingleExit, Terminal
      edge.py      Edge: one route (source, outcome, target)
      graph.py     Graph: the edges; reachability + validation
      builder.py   GraphBuilder: Graph -> LangGraph
    triage.py      the triage route list + `triage_graph`
    nodes/         one module per node, each ending in its production instance;
                   a node with helpers of its own is a folder with node.py:
      retrieve/    node.py (HybridRetrieveNode), bm25.py, vector.py, fusion.py:
                   pure (session, …) -> list[FrozenHit]
      candidate_pool/ node.py (CandidatePoolNode), links.py (link expansion;
                   RerankNode also reads `article_titles` from it), shortlister.py
                   (ABC + cross-encoder/lexical + import-time selection)
      rerank/      node.py (RerankNode, the floor gate), reranker.py (JevReranker)
```

The layering is enforced by `tests/test_boundary.py`.

A value type that sits in `TriageState` lives in `graph/state.py`, even if only
one node produces it (`RankedChunk`, `Candidate`), so every node and the
builder can import it. A type that crosses the HTTP boundary goes in
`schemas.py` instead.

## The node contract

A node owns exactly four things: its **name** (derived from the class), its
**`__call__`** (the work), its **`decide()`** (which outcome it reached), and its
**`Outcome`** enum. It never knows what runs after it. Routing lives in
`graph/triage.py`.

- **Class name `<Something>Node`** gives `name = "something"` (snake_case), which is
  what shows up in traces. The module's production instance is a variable with that
  same name: `rerank = RerankNode()`. It is the only instance: `BaseNode` raises
  `TypeError` on a second construction, so tests import it too.
- **`__call__(self, state: TriageState) -> dict[str, Any]`** returns only the keys it
  changed. It **never writes to `self`**: one instance is shared across FastAPI's
  threadpool.
- **`__init__` only for setup that should fail at boot**, such as `InferNode` loading
  its prompt file. Not for injecting dependencies.
- **Single exit:** no `Outcome` and no `decide()`. It inherits `SingleExit` and is
  routed with `SingleExit.DONE`.
- **Multiple exits:** a module-level `class <Name>Outcome(StrEnum)` with UPPER_SNAKE
  members and PascalCase values that mean something in the business
  (`EVIDENCE_BELOW_FLOOR = "EvidenceBelowFloor"`). Assign it with
  `Outcome = <Name>Outcome`, and override
  `decide(self, state: TriageState) -> <Name>Outcome`. The return annotation **must**
  be the module-level enum, not a bare `Outcome`: LangGraph resolves the annotation
  against module globals.
- `decide()` runs **after** the update is merged, so it reads fresh state.

Exemplars: `graph/nodes/rerank/node.py` (branching), `graph/nodes/injection.py`
(branching, pure CPU), `graph/nodes/retrieve/node.py` (single-exit, providers),
`graph/nodes/infer.py` (boot-time `__init__`, LLM failure).

## Providers: singletons, used directly

Nodes import the provider singletons and call them. Nothing is passed in.

| Provider | How a node gets it | Why that way |
|---|---|---|
| `db` | `from ai_engine.core.db.client import db` | the `use_db` fixture patches the name in each node module |
| `embedder` | `from ai_engine.core.providers.embeddings import embedder` | the `use_embedder` fixture patches it per module |
| `shortlister` | `from ai_engine.graph.nodes.candidate_pool.shortlister import shortlister` | the `use_shortlister` fixture patches it per module |
| `reranker` (Jev) | `from ai_engine.graph.nodes.rerank.reranker import reranker` | the `use_reranker` fixture patches it per module |
| chat LLM | `from ai_engine.core.providers import clients`, then `clients.chat.complete(…)` | `use_llm` patches `clients.chat` once. Importing `chat` by name would bypass the patch |

**When a node module starts reading a provider, add that module to the matching
`use_*` fixture in `tests/conftest.py`.** Otherwise tests quietly hit the real
provider, or fail in confusing ways.

## Config

- A tunable becomes a field on `Settings` in `core/config.py` (type only, **no
  default**) and an entry in the repo root's `.env.example` with its value and
  a comment saying what it trades off. `tests/test_config.py` fails if the two
  disagree. Read `settings.x` at the point of use, and don't pass it through
  constructors.
- ai-engine **never reads `thresholds.yaml`**. core-api owns calibration. The
  number the graph needs per request, `retrieval_floor` (on Jev's scale),
  arrives in `AIRunRequest` and is read **from state**.
- A limit is not a threshold. `fusion_candidate_limit` slices a list ordered by RRF,
  and that's fine. Comparing an RRF *score* against a number is not (ADR-0005).
- Safety fallbacks are **never** settings (the `(False, "high")` deny fallback of
  the KB-policy lookup in `EmitSignalsNode`). Properties of a model or schema are commented constants
  (`EMBED_DIM`). Lexicons stay in code (`NEGATIONS`, `PATTERNS`).

## Failure semantics

Every failure path has to end with a human looking at the ticket, under a reason the
dashboard can count. There are three shapes, and new code picks one on purpose:

| Situation | Shape | Where it ends | Example |
|---|---|---|---|
| Infrastructure the node needs is down (DB, embedder, reranker) | **let it raise** | graph aborts → 500 → core-api `ai_engine_unavailable` → HITL | `HybridRetrieveNode`, `RerankNode` |
| A failure the graph should carry forward and name | return `degraded_reason="<ReasonCode value>"`, leave outputs at safe defaults | `emit_signals` still runs; core-api maps the reason in `apps/tickets/utils/pipeline.py` | `InferNode` on `AllLLMDownError` → `"all_llm_down"` |
| Bad model output | not an exception: `proposal=None` | `validate` records `schema_valid=False` → HITL | `InferNode` JSON/schema failure |
| A best-effort, log-only lookup | catch broadly, return the **deny** value | signals are still emitted | the KB-policy lookup in `EmitSignalsNode` |

What the node must **never** do: turn an infrastructure failure into an empty or
"clean" result, such as `[]` candidates, a zero vector, or checks marked as passed.
An empty KB and a KB that couldn't be reached are different facts, and they reach
HITL under different reason codes.

`emit_signals` runs on every path. It must not raise. A 500 from it means core-api
gets no signals at all.

## Database

- Read only through `db.all(statement)` or `db.first(statement)`. Each borrows a
  pooled connection for that one statement, so no code holds a session, and none can
  be held across an HTTP call to a model. `FakeSessionSource.events` lets a test
  prove it (`test_retrieve.py::test_no_db_connection_is_held_while_embedding`).
- Use SQLAlchemy 2.0 `select()` against `core/db/tables.py`. Declare only the columns
  you read.
- The role is `ai_engine_ro`, which has SELECT on `kb_articles`, `kb_chunks` and
  `fewshot_examples` and **nothing else**. A new table means a new grant in
  `infra/migrations/sql/` *and* an ADR-0004 conversation. It is not a code change.
- No `session.add/commit/flush/delete`, and no `create_all`.
  `tests/test_db_tables.py` greps the source for these.

## State (`graph/state.py`)

- `TriageState` is a frozen pydantic model with `extra="forbid"`, and its fields are
  flat.
- New fields go **under the `# <NodeClassName>` comment** of the node that writes
  them, in graph order. One field has one owner.
- A default means "this node has not run": `[]`, `None`, `0`, `False`. For a
  validation check, the default must mean **failed**. A refuse-before-LLM run skips
  the validator, and `emit_signals` must not report checks that nobody ran as passing.
- List fields have **no reducer**. Add `Annotated[list, operator.add]` only if
  several nodes genuinely accumulate into the same list.
- Only masked text reaches the graph. The one exception is `/v1/pii/detect`
  (ADR-0012), which never enters the graph and never logs its input or the
  model's reply. Nodes read `ticket.subject_masked` and
  `ticket.body_masked`. Nothing else about a ticket is available here, and it should
  stay that way.

## What ai-engine never does

- Decide a `Branch`, score trust, or check auto-reply authority. core-api does all of
  those (ADR-0001, ADR-0002).
- Write to any database (ADR-0004).
- Feed `llm_self_confidence` into anything but the log-only field (ADR-0003).
- Retry a model call, fall back to another provider, or cycle the graph.
