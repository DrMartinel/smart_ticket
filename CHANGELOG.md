# Changelog

Notable changes to Smart Ticket Triage.

Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).
The project is pre-release and unversioned — no tags exist yet, and every
package declares `0.1.0`. Sections below are grouped by the change set that
landed, newest first.

Behaviour changes are called out explicitly, because this system's
correctness is mostly about what it does when things go wrong: a change
that moves a failure path is more significant here than a new feature.

## [Unreleased]

### Changed

- **Chat runs on whatever `CHAT_CLIENT_PROVIDER` says; no fallback.**
  Behaviour change: `CHAT_CLIENT_PROVIDER` takes `vllm` | `openai` |
  `anthropic` | `gemini`, and `CLOUD_PROVIDER` is gone. `openai` is OpenAI's
  cloud API for chat only, configured by the `CLOUD_*` settings;
  `EMBED_CLIENT_PROVIDER` and `RERANK_CLIENT_PROVIDER` are gone, as embeddings
  and reranking always run on vLLM. A provider that fails
  its two attempts degrades the ticket to HITL as `all_llm_down`;
  `cloud_fallback_to_self_host` is no longer produced, and
  `LLMResult.degraded_reason` and every `fallback` parameter are gone.
- **ai-engine's providers are module-level objects built at import time.**
  `providers/llm/models.py` builds `chat`, `embed`, `rerank` and `self_host`
  from settings at its bottom (the provider classes read their own config),
  and `embeddings.py`, `reranker.py` and `db/client.py` build `embedder`,
  `reranker` and `db` the same way; `providers/factory.py` is gone.
  `CHAT_CLIENT_PROVIDER` is a `Literal` on `Settings`.
  `build_providers()`, `Providers` and `LLM` are gone; main.py imports
  those objects directly. `*_MODEL` / `*_BASE_URL` pick each vLLM model and
  server; an unknown provider fails the boot. The `LLMClient` base class and its providers
  now live together in `providers/llm/models.py`, and `VLLMLLM` and
  `OpenAILLM` are separate classes. `VLLM_CHAT_BASE_URL`, `VLLM_CHAT_MODEL`,
  `VLLM_EMBED_BASE_URL`, `VLLM_EMBED_MODEL` and `VLLM_RERANK_BASE_URL` are
  renamed `CHAT_BASE_URL`, `CHAT_MODEL`, `EMBED_BASE_URL`, `EMBED_MODEL` and
  `RERANK_BASE_URL` in both services. No behaviour changed with the defaults
- **`LexicalEmbedder` and `CrossEncoderReranker` own their tasks; `LLMClient` only carries
  requests.** `LexicalEmbedder` and `CrossEncoderReranker` build the `/embeddings` and `/rerank`
  payloads, parse the replies and enforce their contracts (EMBED_DIM, one score
  per passage in input order), calling `models.embed` / `models.rerank`
  via `LLMClient.request()`, implemented by `VLLMLLM`. `LLMClient` and its
  providers live together in
  `providers/llm/models.py`. `StubEmbedder` and `LexicalReranker` are
  standalone offline classes for CI, not subclasses. `VLLMEmbedder`, `VLLMReranker` and
  `providers/base.py` are gone. No behaviour changed
- **The in-process cross-encoder is removed (ADR-0009).** `CrossEncoderReranker`,
  `_load_cross_encoder`, the `reranker_revision` / `reranker_use_fp16` settings,
  the `FlagEmbedding` dependency (and torch with it) and the weight bake in the
  ai-engine Dockerfile are gone. *Behaviour change:* `RERANKER_PROVIDER` accepts
  `vllm` or `lexical` and now defaults to `vllm` everywhere, so reranking needs
  vllm-rerank running. `RERANKER_REVISION` now pins the vllm-rerank checkpoint
- **core-api uses self-hosted vLLM instead of Ollama (ADR-0009).** Tier-2 PII
  NER calls `/v1/chat/completions` on `CHAT_MODEL` with a JSON Schema
  (`ollama_ner`/`OllamaError` are now `llm_ner`/`NERError`); embeddings call
  `/v1/embeddings` on `EMBED_MODEL`. `OLLAMA_*` settings are replaced by
  `VLLM_*` and `MODEL_TIMEOUT_SEC` / `MODEL_CONNECT_TIMEOUT_SEC`, and the
  `ollama` compose profile is gone. *Behaviour changes:* masking runs on a
  different model and must be re-checked on real tickets; stored vectors must
  be re-embedded; an unknown `EMBEDDING_PROVIDER` now raises (→
  `embedding_unavailable`) instead of silently using Ollama; a NER reply with
  no content now fails closed to `MASK_FAILED` — it used to default to `[]`,
  i.e. "no PII found"; the fallback reason is now `cloud_fallback_to_self_host`
- **ai-engine no longer uses Ollama; self-hosted vLLM replaces it (ADR-0009).**
  `OllamaLLM`, `OllamaEmbedder`, the `ollama_*` settings, `SELF_HOST_PROVIDER`
  and the `langchain-ollama` dependency are removed. `VLLMLLM` is always the
  self-hosted link, and `EMBEDDING_PROVIDER` now defaults to `vllm`.
  *Behaviour change:* real inference and embeddings need the `vllm` compose
  profile running, and the KB must be re-embedded through vLLM. core-api still
  uses Ollama for PII masking and ticket embeddings (since migrated, above)
- **Model backends live under `core/providers/`.** `core/llm/` is gone: the
  LLM client, chat-model factories and circuit breaker moved to
  `core/providers/llm/`, the `LLMClient` seam moved into
  `core/providers/llm/models.py`, and the prompts and their loader moved to
  `core/prompts/`. No behaviour changed
- **One LLM class hierarchy.** `LLMClient` owns the breaker, retry, fallback
  and reply parsing; `OllamaLLM`, `OpenAILLM`, `AnthropicLLM` and `GeminiLLM`
  subclass it and implement only `_build()`. `DefaultLLMClient`,
  `ChatModelFactory` and `_FlatTimeoutCloudFactory` are gone, and the fallback
  is passed to the primary provider (`AnthropicLLM(..., fallback=OllamaLLM(...))`).
  `complete()` now requires `timeout` — the infer node always passed one. No
  behaviour changed
- **`GraphBuilder` raises on a node update key the state schema lacks.**
  LangGraph silently dropped it, so a misspelled key looked like it worked;
  a non-dict return raises too
- **`TriageState` is flat.** `InjectionVerdict` and `ValidationResult` are
  gone: `injection` is now `injection_detected` / `injection_matched_patterns`,
  and each validation check is a top-level field whose default reads as
  "failed", replacing `ValidationResult.all_failed()`. No routing behaviour
  changed
- **`RankedChunk` moved to `core/retrieval/rerank.py`**, so
  `TriageState.reranked` is typed `list[RankedChunk]` instead of `list[Any]`
  and is validated like every other field
- **The LLM client now uses LangChain chat models for transport; retry,
  fallback and the circuit breaker are unchanged and still ours.**
  `core/llm/client.py` lost ~90 lines of hand-written httpx and two bespoke
  response schemas. It did NOT adopt `.with_retry()` / `.with_fallbacks()`:
  those give no supported signal for *which* link answered, which would drop
  `degraded_reason="cloud_fallback_to_ollama"` and make a degraded answer look
  clean. `complete()`'s signature, both exception types and the
  `degraded_reason` mapping in `infer.py` are untouched (ADR-0007)
- **`OllamaEmbedder` calls through `langchain-ollama`.** The `Embedder` seam,
  the raise-don't-degrade contract and the `EMBED_DIM` width check all stay on
  our side — langchain has no opinion about the width our pgvector column was
  migrated to
- **LLM provider selection moved to startup.** `DefaultLLMClient` used to
  re-read `settings` on every call to decide whether a cloud link existed;
  `build_providers()` now resolves the chain once and injects it
- **Token counts come from `usage_metadata`.** *Behaviour change:* an absent
  and an explicitly-null token count are no longer distinguishable. The old
  code rejected null as malformed; both now read as 0, so a provider emitting
  nulls undercounts against the token budget instead of failing loudly
  (ADR-0007)
- **ai-engine's four read queries are built with SQLAlchemy 2.0 instead of
  SQL strings** (BM25, vector, few-shot, KB policy). Declarative table classes
  in `core/db/tables.py` list only the queried columns; core-api still owns
  the schema. The `ConnectionSource` ABC is gone — it had one real
  implementation — and `PsycopgConnectionSource` in `core/providers/db.py` is
  now `SqlAlchemySessionSource` in `core/db/client.py`, beside the table
  declarations (NullPool, still one connection per use, still no socket at
  construction, still built only by `build_providers()`). The compiled SQL for
  every query is now under test, including the filters that keep retracted
  and expired few-shot examples out of the prompt (ADR-0008)
- **`LLMClient` moved from `core/providers/base.py` to `core/llm/base.py`,**
  beside its implementation; `providers/base.py` keeps `Embedder` and
  `Reranker`. Import paths change; behaviour does not
- **Removed code that existed only to serve tests from ai-engine.**
  - Parameters nothing in production passed: `ValidateNode(negations=)` and
    `InjectionNode(patterns=)` (now module constants `NEGATIONS` /
    `PATTERNS`), `InferNode(attempt_headroom_divisor=)` (now a module
    constant), `DefaultLLMClient(circuit=)` (it uses the process-wide
    `CIRCUIT`; tests swap that module attribute), and
    `GraphBuilder.compile(checkpointer=)` (always None)
  - Defaults only tests relied on: `DefaultLLMClient`'s `fallback` and
    `AnthropicChatModelFactory`'s `base_url` are now required
  - Accessors only tests read: `GraphBuilder.routes`, `GraphBuilder.entry`,
    `CircuitBreaker.state`, and `Candidate.rrf_score` (with its formula test;
    fusion ordering is still tested)
  - Comments that justified code by pointing at tests now state the
    production reason, or were removed where there was none
- **Embeddings are bound as `'[...]'` text**, via `pgvector.sqlalchemy`,
  rather than hand-built literals cast with `::vector`

### Added

- **Self-hosted vLLM backend (ADR-0009).** `SELF_HOST_PROVIDER=vllm`,
  `EMBEDDING_PROVIDER=vllm` and `RERANKER_PROVIDER=vllm` direct the chat LLM,
  embeddings and reranking to vLLM's OpenAI-compatible APIs (`VLLMLLM`,
  `VLLMEmbedder`, `VLLMReranker`), with a `vllm` compose profile running one
  server per model. Code only — not yet run against a
  real server: the rerank score is unverified against the in-process
  cross-encoder, and switching the embedder needs the KB re-embedded
- **Claude and Gemini as cloud providers**, alongside the existing
  OpenAI-compatible link. `CLOUD_PROVIDER` selects between `openai`,
  `anthropic` and `gemini`; Ollama remains the fallback behind whichever is
  chosen. New `CLOUD_MAX_OUTPUT_TOKENS` caps a single cloud generation —
  Anthropic defaults to 128000, enough for a runaway generation to eat the
  per-ticket latency budget
- **Cloud misconfiguration is now fatal at boot.** `CLOUD_BASE_URL` without a
  key, `openai` without a base URL, `gemini` *with* one (the Google client has
  no endpoint override, so it would be silently ignored), and any unknown
  `CLOUD_PROVIDER` all fail the boot. Previously a half-configured cloud link
  was invisible: the service ran Ollama-only while the operator believed
  otherwise

### Fixed

- `evals/suites/golden_utils.py` read the golden set without an explicit
  encoding, so the eval suite could not run on Windows at all — the Vietnamese
  fixtures failed to decode under cp1252

### Known limitations

- `anthropic` and `gemini` cannot honour the 3s-connect / long-read split.
  Their timeout fields are plain floats with no injectable HTTP client, so they
  take a single flat timeout. Ollama — the provider the split was calibrated
  for — is unaffected (ADR-0007)
- The Anthropic API has no JSON output mode, unlike the other three providers.
  Under `CLOUD_PROVIDER=anthropic` only the system prompt keeps the reply
  parseable; unparseable output still degrades to HITL rather than 500ing

### Changed

- **`sentence-transformers` is a required dependency rather than an optional
  extra, so the cross-encoder is always available.** `RERANKER_PROVIDER` still
  defaults to `lexical`; what changed is that switching to `cross_encoder` is
  now one environment variable and a restart, where before it silently could
  not work in a container at all. Cost: torch is installed everywhere, so
  images and CI are several GB heavier.
- **The cross-encoder's weights are baked into the image.** It always pulls
  `bge-reranker-v2-m3` into a layer, and the container runs `HF_HUB_OFFLINE=1`.
  Previously the first ticket to reach the reranker downloaded ~2.3GB over the
  network mid-request, and repeated it on every container recreate, since the
  HF cache lived on the ephemeral filesystem. New `RERANKER_MODEL` /
  `RERANKER_REVISION` settings must agree with the build args of the same name;
  a mismatch is a hard error rather than a silent download. Pin
  `RERANKER_REVISION` to a sha — left at `main`, an upstream commit swaps the
  checkpoint, and with it the score distribution `retrieval.floor` was written
  against, without failing loudly (ADR-0005). Costs: +~3-4GB on the image, and
  the build now depends on the HF hub being reachable.
- **`CrossEncoderReranker` loads its model in `__init__` instead of lazily on
  first `score()`**, so the load lands at uvicorn import time and no ticket
  pays it. *Behaviour change:* with `RERANKER_PROVIDER=cross_encoder` the
  process blocks for a few seconds at boot and serves no `/healthz` until the
  model is resident, and an unusable model cache kills the container rather
  than degrading one ticket to HITL. Intended — there is no correct fallback,
  since the lexical scorer is a different calibration (ADR-0005), so the loud
  failure is the right one.
- The load lock and `_model_or_load` are gone with it. They existed because
  `analyze` is a sync `def`, so FastAPI served concurrent cold requests from a
  threadpool against one shared instance and each racing request built its own
  multi-GB model. Constructing eagerly removes that race by construction rather
  than by locking.
  `test_cross_encoder_builds_its_model_exactly_once_at_construction` keeps the
  concurrent scoring threads, so restoring a lazy load without a lock fails
  there rather than as an OOM in production.
- Unit tests never load real weights: an autouse fixture in
  `services/ai-engine/tests/conftest.py` stubs the loader, so a test that
  selects `cross_encoder` does not also pull a 2.3GB checkpoint that no CI
  runner has.
- `build_providers()` no longer promises that *every* constructor is pure; the
  cross-encoder is a documented exception and the rest are unchanged.
- **Documented, not fixed: `retrieval.floor` is calibrated for a provider that
  is not the default.** `floor = 0.45` is a CROSS-ENCODER score (ADR-0005), but
  `lexical` scores `|query ∩ passage| / |query|` — a token-overlap ratio. The
  default configuration therefore compares that threshold against a fraction of
  matching words: a different question, decided silently, with no error and no
  test that can see it. Now written down at every point it matters
  (`thresholds.yaml`, `config.py`, `.env.example`, `eval-gate.yml`), and the
  calibrated provider is finally reachable. Resolving it needs measured
  cross-encoder scores *and* a way for core-api — which sends `retrieval_floor`
  and cannot see which provider ai-engine selected — to know which calibration
  applies. See `docs/TODO.md` item 4.

### Fixed

- **`RERANKER_PROVIDER=cross_encoder` could not work in the container at all.**
  The image never installed `--extra cross-encoder`, and
  `CrossEncoderReranker`'s constructor was pure, so the container booted green,
  passed `/healthz`, and died with `ModuleNotFoundError` on the first ticket
  that reached `score()` — after core-api had already handed it work. Same
  silent-until-first-use shape as the typo'd provider value fixed earlier.
  Fixed at the root: sentence-transformers is a required dependency now, and
  the model loads at startup, so a broken environment fails the boot rather
  than a ticket.

### Added

- **CI/CD actually runs now.** There was no `.github/` directory, so
  `infra/ci/eval-gate.yml` — a complete, well-designed workflow — had sat in
  a path GitHub never reads for the project's entire history. Moved to
  `.github/workflows/eval-gate.yml` and given a `push: branches: [main]`
  trigger alongside the existing `pull_request` one, since this repo
  currently merges straight to main.
- `.github/workflows/lint.yml` — `ruff check` and `ruff format --check`,
  with no services attached so it returns in under a minute.
- `.github/workflows/publish-images.yml` — builds the three container
  images and pushes them to GHCR on merge to main, tagged with the commit
  SHA and `latest`. Three images rather than five: `core-api`, `worker` and
  `beat` share one image and differ only by `command`. No deploy step —
  there is no deployment target in the repo, so this produces artifacts and
  leaves rollout manual. It runs its own unit-test job instead of chaining
  behind the eval gate, which is knowingly red on the `other` F1 and would
  otherwise block publishing forever.

### Changed

- **Definitions moved into `ai_engine/core/`.** Settings, graph state, node
  base classes and provider Protocols now live apart from the code that
  implements them. Import paths changed, with no compatibility shims:
  `ai_engine.config` → `ai_engine.core.config`,
  `ai_engine.graph.state` → `ai_engine.core.state`,
  `ai_engine.graph.base` → `ai_engine.core.node`,
  `ai_engine.graph.budget` → `ai_engine.core.budget`,
  `ai_engine.providers.protocols` → `ai_engine.core.providers`.
  Nodes, providers, retrieval, the LLM client, graph wiring and data models
  (`Candidate`, `RankedChunk`, `LLMResult`, …) are unchanged. No behaviour changed.
- **Providers, retrieval and the LLM client moved into `core`.** `core` is now
  everything the nodes are built on, definitions and implementations alike;
  only `graph/` and `main.py` sit outside it, and `core` never imports from
  them. Import paths changed, with no shims:
  `ai_engine.providers` → `ai_engine.core.providers`,
  `ai_engine.retrieval` → `ai_engine.core.retrieval`,
  `ai_engine.llm` → `ai_engine.core.llm` (prompts now under
  `core/llm/prompts/`), `ai_engine.db` → `ai_engine.core.providers.db`, and
  the seam ABCs `ai_engine.core.providers` → `ai_engine.core.providers.base`.
  `TriageState.candidates` is now typed `list[Candidate]`. No behaviour changed.
- **`TriageState` is a pydantic model.** `TriageState`, `InjectionVerdict`
  and `ValidationResult` (`core/state.py`) are frozen `BaseModel`s instead of
  `TypedDict`s. Nodes read `state.field` and still return partial update
  dicts; unset progressive fields have defaults, and a missing `validation`
  reads as `ValidationResult.all_failed()`, as before.
  - **Behaviour change:** LangGraph now validates the merged state before each
    node. A node returning a wrong-typed value aborts the run with a
    `ValidationError` (a 500 → `AIEngineUnavailable` → human) instead of
    passing the bad value onward.
  - `GraphBuilder.compile` passes `input_schema=state_schema` to every node.
    Without it LangGraph takes each node's input schema from its `state:`
    annotation, which made `Terminal` (annotated `TriageState`) reject the
    state of any other graph.
  - Unchanged: an update key that is not a field is still silently dropped by
    LangGraph. `Terminal`'s docstring previously claimed otherwise; corrected.
  - Tests build state through `make_state`; partial dict states are gone.
- **ai-engine value objects are pydantic models.** `LexicalHit`,
  `VectorHit`, `Candidate`, `RankedChunk` and `LLMResult` are frozen
  `BaseModel`s instead of dataclasses; `Providers` and `CircuitBreaker` are
  unchanged. They stay internal to ai-engine — not
  `packages/contracts`, which is only for the core-api ↔ ai-engine wire.
  - **Behaviour change — malformed LLM responses.** A provider answering 200
    with a null `response` (Ollama) or `content` (cloud) used to reach the
    infer node as `text=None`, fail JSON parsing and go to HITL as a *schema*
    failure, blamed on the model. `LLMResult` now rejects it inside the
    client, which retries, falls back cloud → Ollama, and raises
    `AllLLMDownError` → `degraded_reason="all_llm_down"`, and counts it
    against the circuit breaker. Still HITL, under the reason code that
    matches what happened. The client catches `ValidationError` on both the
    primary and fallback calls; without that it would have escaped as a 500.
  - Provider bodies are now parsed with pydantic models
    (`model_validate_json`) instead of indexing `resp.json()` by hand, so the
    same path covers every malformed reply. **Previously a 500:** a non-JSON
    body, a cloud reply with missing or empty `choices` or a null `usage`, and
    a null token count from either provider. **Previously a schema failure:**
    an Ollama reply with no `response` key, which defaulted to `""`. A token
    count that is *absent* still defaults to 0 (Ollama omits
    `prompt_eval_count` for a cached prompt); a *null* one is rejected rather
    than counted as 0, so the token budget is never silently undercounted.
- **Provider seams are ABCs, not Protocols.** `Embedder`, `Reranker`,
  `LLMClient` and `ConnectionSource` (`core/providers.py`) are abstract base
  classes; every implementation and test fake subclasses its seam. Nothing
  type-checks this repo, so a Protocol was enforced by nothing — a provider
  with a misnamed method failed on the first ticket. It now raises
  `TypeError` when `build_providers()` constructs it at import time, so the
  process refuses to boot. Only method presence is checked, not signatures.
- **Settings are read where they are used, not passed down from `main.py`.**
  Retrieval functions (`bm25_search`, `vector_search`,
  `reciprocal_rank_fusion`), nodes, providers and `PsycopgConnectionSource`
  read `ai_engine.config.settings` themselves; their constructors and
  signatures now take collaborators only, and `build_providers()` takes no
  argument. `InferNode` resolves its prompt from `settings.prompt_version`
  at construction. `reciprocal_rank_fusion` lost its `k=60` default — a
  second copy of `settings.rrf_k`, and `InferNode`'s
  `min_attempt_timeout_sec=5.0` default moved to `Settings`. Tests override values with
  `monkeypatch.setattr(settings, ...)`. No behaviour changed.
- **Graph wiring moved from the `FLOW` table to `GraphBuilder`.** Routes
  now map an outcome of a node *instance* to the next instance —
  `g.route(rerank, RerankNode.Outcome.EVIDENCE_BELOW_FLOOR, emit)` — and live
  on the builder, never on node classes or `Outcome` members (which
  single-exit nodes share). The triage topology is `wire_triage(...)` in
  `graph/flow.py`, taking every node as a required keyword; `main.py` and
  the `triage_nodes` fixture (now a dict) both go through it.
  - Removed: `FLOW`, `ENTRY`, the `Flow` and `Target` types and `compile_graph`; the
    `isinstance` matching of instances to flow classes.
  - Validation: bad routes raise as declared (class passed instead of
    instance, foreign or duplicate outcome); `compile()` raises on unrouted
    outcomes, unreachable routed nodes and same-name instances. Outcome
    membership is now checked by identity — previously a same-valued member
    of another `StrEnum` passed.
  - A test fake subclass now registers under its own name (`fake_infer`),
    not the real node's. Existing production node names are unchanged.
  - **`Terminal` is now a real node** (`graph/base.py`), not a marker class:
    routes target `Terminal()`, it runs as a no-op `terminal` step, and
    `compile()` gives it the graph's only edge to END. Traces and streamed
    step names gain a final `terminal` step. Routing out of a Terminal, or
    a graph with no reachable Terminal, raises at startup.
  - No routing behaviour changed.
- **Graph wiring moved to a validated flow table.** Every node subclasses
  `BaseNode` (`graph/base.py`), reports a domain `Outcome` from `decide()`,
  and never names its successor. The topology lives in one `FLOW` dict in
  `graph/flow.py`; `compile_graph` in `graph/build.py` raises at startup
  on an unrouted outcome, a dangling target or an unreachable node, and is
  the only place a class becomes a LangGraph node name. `main.py` builds
  the providers and node instances inline and calls `compile_graph` once at
  import time. See `docs/graph-node-architecture.md`.
  - **Node names changed** — they are now derived from class names:
    `detect_inject` → `injection`, `retrieve` → `hybrid_retrieve`,
    `select_shots` → `select_fewshots` (`rerank`, `infer`, `validate`,
    `emit_signals` unchanged). The graph has no checkpointer, so nothing
    persisted references the old names; anything reading LangGraph step
    names (traces, streaming) sees the new ones.
  - Removed: `GraphDeps` and `build_graph()` (tests build the node list
    with the `triage_nodes` fixture and swap one instance for a subclass of
    the real node), the `GraphNode` Protocol, and the
    `_after_injection` / `_after_rerank` / `_after_validate` routers (now
    `decide()` on `InjectionNode`, `RerankNode`, `ValidateNode`).
  - The budget guard is now a base class: `BudgetedNode` (`graph/budget.py`)
    wraps each subclass's own `__call__` at class definition so the budget
    is checked before it runs; nodes keep the ordinary
    `__call__(self, state) -> dict` signature. `HybridRetrieveNode`,
    `RerankNode` and `InferNode` inherit it. `check_budget()` now raises
    `BudgetExceeded`, which the wrapper catches.
  - **Behaviour change (output shape only):** an over-budget node now
    returns just `{"degraded_reason": "budget_exceeded"}` instead of also
    `candidates: []` / `reranked: []` / `proposal: None`. Every reader
    defaults those keys to empty, so routing and the final response are
    unchanged — pinned by an end-to-end graph test in `test_budget.py`.
  - No routing behaviour changed: refuse-before-LLM and the `iteration < 2`
    retry cap are identical. `ValidateNode` splits the old "otherwise"
    branch into `SchemaValid` and `RetriesExhausted`, both routed to
    `emit_signals`.
- Ruff's rule selection is now pinned explicitly in `pyproject.toml`
  (`select = ["E4","E7","E9","F"]`) and the binary pinned in the workflows.
  Ruff's implicit default is not stable across releases: this repo is clean
  under the historical one, but ruff 0.16 reports 104 findings on unchanged
  code. Without the pin a ruff upgrade turns CI red overnight. Bump the two
  pins together.
- `ruff format` applied across the workspace (66 files, mechanical only).
  Comments are not rewrapped, so the prose explaining spec/ADR reasoning is
  untouched.

- **Graph nodes are now classes.** All seven nodes in
  `services/ai-engine/src/ai_engine/graph/nodes/` take their collaborators
  and configuration through `__init__` instead of reaching for module
  globals and re-reading `settings.*` on every call. `graph/build.py` is
  now the only place nodes are constructed and wired, via a `GraphDeps`
  dataclass (since replaced by the flow table, above). `build_graph()` remains callable with no arguments, so
  `main.py` is unchanged.
- **Providers sit behind Protocols.** `providers/protocols.py` defines the
  four seams between a node and the outside world — `Embedder`,
  `Reranker`, `LLMClient`, `ConnectionSource` — with class implementations
  behind each. Nodes depend on the Protocol, never on a concrete provider
  module, which is what makes them testable with no database, no Ollama
  and no model download.
- **Provider selection happens once, at startup.** `providers/factory.py`
  is the single place `EMBEDDING_PROVIDER` and `RERANKER_PROVIDER` are
  read.
- The cross-encoder's first model load is serialized behind a lock.
  `analyze` is a sync `def`, so FastAPI serves concurrent requests from a
  threadpool against one shared instance; previously each racing cold
  request built its own multi-GB model. The lock is not held across
  `predict()`. Peak RAM under a cold-start stampede goes from N× to 1×;
  the failure signature changes from OOM to a slow first batch.

### Fixed

- **`settings.prompt_version` is now honored.** `infer.py` read
  `classify.v3.md` by a hardcoded filename at import time, so bumping the
  setting changed what logs and responses *claimed* had run without
  changing what actually ran. Prompts now resolve through
  `llm/prompt_store.load_system_prompt()`. Resolves to the same file
  today, so no output changes.
- **An unknown provider selector is now fatal at startup** instead of
  falling through silently. A typo'd `RERANKER_PROVIDER` used to degrade
  to the lexical reranker, whose scores are a different calibration from
  the cross-encoder distribution `retrieval.floor` is fitted against
  (ADR-0005) — the refuse-before-LLM rate would be wrong and nothing would
  look broken.
- **The offline eval gate had never run.** `infra/ci/eval-gate.yml`
  listed `evals/suites/test_build.py`, which does not exist; pytest exits
  4 on a missing path. Graph-structure tests live in
  `services/ai-engine/tests/test_build.py` and run in the ai-engine step.
- A missing prompt file now fails in `build_graph()` rather than at
  `import ai_engine.graph.nodes.infer`. Still at boot; test collection no
  longer touches the filesystem.
- `load_system_prompt` rejects path separators, so if per-request prompt
  selection ever lands it cannot become an arbitrary file read.

### Added

- Four values that were hardcoded became configuration:
  `fusion_candidate_limit` (was `candidates[:10]`),
  `quote_fuzzy_threshold` (was `FUZZY_THRESHOLD = 0.95`), and
  `reranker_model` in `Settings`; the injection pattern set and negation
  lexicon became constructor parameters with module-level defaults. The
  latter two stay in code rather than `Settings` — they are linguistic
  data, like `patterns.py` holds the PII regexes, not tunable numbers.
- ai-engine unit tests went from 38 to 94, covering failure paths that
  were previously unreachable without live infrastructure: a DB outage
  during the KB-policy lookup degrading to deny-by-default, an embedder
  outage propagating rather than looking like an empty KB, circuit-open
  and all-providers-down mapping to their exact reason codes, and every
  budget-exhausted path spending nothing. `tests/conftest.py` provides a
  fake per Protocol.
- A test pinning ADR-0005: rerank output order follows the cross-encoder
  score, not the RRF order the candidates arrived in. This invariant had
  no test and does not fail loudly when broken.

### Removed

- The `embed_text`, `rerank`, `get_connection` and `chat_complete`
  module-level functions in ai-engine, now that every caller receives its
  collaborator through a constructor. core-api's own `embed_text` is a
  separate module, duplicated deliberately per ADR-0004, and is untouched.
- `services/ai-engine/tests/__init__.py`. With it present, ai-engine's and
  core-api's `conftest.py` both resolved to the module name
  `tests.conftest` and a whole-workspace `pytest` run died at collection.
  See the note in `pyproject.toml` — do not add it back.

### Known issues

- `other` category F1 is 0.75 against a 0.85 floor (precision 1.00, recall
  0.60). Real and documented in `evals/baselines/baseline.json`; see
  `docs/TODO.md` §3.
- `AIRunRequest.prompt_version` is echoed back in `AIRunResponse` while the
  graph runs whatever `settings.prompt_version` resolves to, so the
  response asserts a version that did not run. Corrupts audit trail and
  eval attribution. `docs/TODO.md` §6a.
- Trust-score coefficients are a hand-set prior, not fitted. `t_auto` and
  `t_route` are placeholders pending ≥500 shadow pairs.

## Earlier

Reconstructed from commit history; this file did not exist at the time.

### Fixed

- The local-LLM path made reliable, and three signal bugs corrected
  (`a82c13a`). Includes diacritic folding in the lexical reranker, without
  which an unaccented Vietnamese ticket scored ~0.04 against an accented KB
  article instead of ~0.75 — far below `retrieval.floor`, sending every
  such ticket to a human as "nothing in the KB matches".

### Added

- Fallback mechanism for embedding outages (`16e9abd`).
- Project README, architecture overview, and an onboarding reading path
  (`065caa5`, `ada67a7`).
