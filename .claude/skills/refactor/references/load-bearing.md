# Load-bearing: looks removable, isn't

Things a readability pass will be tempted to "clean up" and must not. Each one exists
to stop the LLM gaining authority, a failure passing as success, or a calibration
being silently swapped. The bug each prevents **does not fail loudly**. That is
exactly why it looks removable.

In a refactor audit, anything that matches this list goes under **"considered, left
alone"** with its reason. Change one only when the user asks for that specific item,
and then treat it as a behaviour change, following CLAUDE.md: say so in the PR and
link the ADR being argued against.

Format: **what** — why it exists — *what guards it*.

---

## Repo-wide

- **`proposed_` prefixes on LLM-authored fields.** The asymmetry between
  `draft.proposed_category` and `ticket.category` is the point. *CLAUDE.md rule 5.*
- **`router.py` pure, with thresholds passed in as a parameter.** No I/O, no global
  config, no default arguments. *ADR-0001; `services/core-api/apps/tickets/tests/test_router.py`
  (`test_route_is_deterministic_pure_function`).*
- **`thresholds.yaml` parsed into a Pydantic model at boot.** A malformed file must
  stop core-api starting, not surface at routing time. *CLAUDE.md Gotchas.*
- **No cross-service imports except `contracts`.** ai-engine and core-api never
  import each other's code. *ADR-0004.*
- **Old `ReasonCode` members** (`CIRCUIT_OPEN`). Persisted review items still
  deserialize them. *Comment in `contracts/enums.py`.*
- **Defaults on persisted contract fields** (`GenerationSignals.quote_applicable = True`).
  Rows written before the field existed must still load. *CLAUDE.md rule 4.*
- **`services/web/lib/types/generated.ts`.** It is generated, so never hand-edit it.
  *`packages/contracts/scripts/gen_typescript.py`.*
- **`db_table` names mirroring the spec DDL.** `infra/migrations/sql/` is written
  against those exact names.
- **`--import-mode=importlib`, and no `services/ai-engine/tests/__init__.py`.** A
  whole-workspace pytest run dies at collection without them. *Comment in the root
  `pyproject.toml`.*
- **Separate connect and read timeouts** (3s / 120s). Collapsed, an unreachable
  provider hangs for 120s, while a short read timeout reports a cold model load as
  "down". *Comments in `ai_engine/core/config.py`; CLAUDE.md Gotchas.*
- **Literal topology and route pins in tests** (`services/ai-engine/tests/test_build.py`).
  They are verbose on purpose: a dropped or redirected route has to fail.

## core-api

- **100% branch coverage of `masking.py`.** It is the P0 release gate. *The coverage
  command in CLAUDE.md.*
- **An NER failure resolves to `MASK_FAILED`, never to "no PII found".** This is the
  single worst regression possible. *`services/core-api/apps/tickets/tests/test_masking.py`;
  comments in `masking.py`.*
- **`llm_self_confidence` stays out of the trust score.** *ADR-0003;
  `test_trust_scorer.py::test_llm_self_confidence_does_not_change_score` and
  `::test_llm_self_confidence_excluded_from_features`.*
- **`RunbookProposal` always goes to HITL**, with no threshold and no flag. *ADR-0006;
  `test_router.py::test_runbook_always_hitl_even_with_perfect_signals`.*
- **Hard-gate order in `router.py`.** `mass_incident` comes before the duplicate and
  mask checks. *`test_router.py::test_mass_incident_escalates_before_mask_failed_check`.*
- **Refuse-before-LLM reports `retrieval_below_floor`, not `schema_invalid`.**
  *`test_router.py::test_refuse_before_llm_reports_retrieval_floor_not_schema_invalid`.*
- **The KB governance path for `auto_reply_allowed`**: manager role, a non-empty
  reason, and a `KbAuthorityLog` row. Seed data takes the same path. *ADR-0002;
  `apps/kb/services.py`; `apps/dbextras/tests/test_seed_demo.py`.*
- **The deny-by-default `_degraded_signals()` in `apps/tickets/services/pipeline.py`**: every check failed,
  `kb_auto_reply_allowed=False`, `kb_risk_tier="high"`.
- **No `decrypt()` call without a `PiiAccessLog` row** in the same transaction, with
  a mandatory non-empty reason. *CLAUDE.md "Current state".*
- **Idempotency key `{ticket_id}:{attempt}` plus `acks_late`.** A redelivered task
  must not send a second auto-reply. *The `tasks.py` and `services/pipeline.py` module
  docstrings.*

## ai-engine

- **`TriageState` is frozen with `extra="forbid"`.** Without that, an in-place
  mutation is silently discarded. *`tests/test_state.py`.*
- **The `_reject_unknown_keys` adapter in `core/build/builder.py`.** LangGraph drops unknown
  update keys silently, so a typo'd key would look like it worked.
  *`test_compiler.py::test_update_key_missing_from_the_schema_raises`.*
- **`input_schema=state_schema` pinned in `GraphBuilder.compile`.**
  *`test_state.py::test_node_annotation_does_not_override_the_graph_schema`.*
- **Outcome membership checked by identity (`is`), not `in`** (`BaseNode.produces`). A `StrEnum` from
  another node with the same value compares equal.
  *`test_compiler.py::test_equal_valued_outcome_from_another_enum_raises`.*
- **Validation-field defaults read "failed"**, and **`_checks(*, …)` has no
  defaults.** `emit_signals` must never report checks that nobody ran as passing.
  *`test_state.py::test_missing_validation_reads_as_every_check_failed`.*
- **`_POLICY_FALLBACK_DENY` is a private constant, not a setting.** No configuration
  may turn a failed lookup into "auto-reply allowed". *Its comment in
  `graph/nodes/emit_signals.py`.*
- **`db.connect()` stays inside the `try` in `EmitSignalsNode._lookup_kb_policy`.**
  A DB outage there must deny by default and not 500 the terminal node.
  *`test_emit_signals.py::test_kb_policy_lookup_failure_denies_auto_reply`.*
- **`Candidate` carries no score.** RRF is derived from rank, so nothing may
  threshold on it. *ADR-0005; `core/retrieval/fusion.py` docstring.*
- **`RerankNode` sorts by the cross-encoder score before truncating.**
  *`test_rerank.py::test_output_order_follows_the_reranker_not_the_rrf_order`.*
- **Vector search orders by raw `cosine_distance`, not by `1 - distance`.** Only the
  raw form can use the HNSW index. *`test_db_queries.py`.*
- **`đ`/`Đ` special-cased in `LexicalReranker._strip_diacritics`.** NFD does not
  decompose them. *`tests/test_reranker_diacritics.py`.*
- **`max_retries=0` and a single `complete()` attempt.** A failed call goes to HITL.
  *`test_llm_client.py::test_a_single_failure_raises_without_retrying`;
  `test_provider_selection.py` tests on "without … sdk retries".*
- **No provider fallback, and an unknown provider name raises at import.** The wrong
  calibration would otherwise look healthy. *`test_provider_selection.py`.*
- **Provider construction opens no socket.** Importing `graph/triage.py` has to work
  without a database. *`test_provider_selection.py::test_building_providers_opens_no_connections`.*
- **`_JSON_OBJECT` response_format on chat clients.** Without it the output turns to
  prose and the HITL rate climbs silently. *Its comment in
  `core/providers/llm/models.py`.*
- **An embedder or reranker failure raises and never returns empty.** An empty result
  reads as "the KB has nothing" rather than "the provider is down".
  *`test_retrieve.py::test_embedder_failure_propagates_rather_than_returning_empty_candidates`.*
- **`load_system_prompt`'s path-traversal check.**
  *`test_infer.py::test_invalid_prompt_version_is_rejected`.*
- **Only three tables are declared in `core/db/tables.py`, and nothing writes.**
  *ADR-0004; `tests/test_db_tables.py`.*
