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

Code comments say only what code does (readability.md §2), so this file and
the ADRs are where these reasons live. Where an entry names a comment as its
guard and that comment is later trimmed, the entry is the record.

---

## Repo-wide

- **`proposed_` prefixes on LLM-authored fields.** The asymmetry between
  `proposal.proposed_intent` and `decision.branch` is the point. *CLAUDE.md rule 5.*
- **`router.py` pure, with thresholds passed in as a parameter.** No I/O, no global
  config, no default arguments. *ADR-0001; `services/core-api/apps/tickets/tests/test_router.py`
  (`test_route_is_deterministic_pure_function`).*
- **`thresholds.yaml` parsed into a Pydantic model at boot.** A malformed file must
  stop core-api starting, not surface at routing time. *CLAUDE.md Gotchas.*
- **No cross-service imports.** ai-engine and core-api never import each other's
  code, schemas included. *ADR-0004, ADR-0010.*
- **The wire schema defined in both services.** It looks like duplication to
  dedupe into a shared module. It is one per deployable on purpose. *ADR-0010.*
- **Router types outside `models.py`.** `Branch`, `ReviewQueue`, `RiskTier` sit in
  `router.py`, not beside the models that store them, so the router never imports
  the ORM. *CLAUDE.md rule 1.*
- **Old `ReasonCode` members** (`CIRCUIT_OPEN`). Persisted review items still
  deserialize them. *Comment on `ReasonCode` in `router.py`.*
- **Defaults on persisted contract fields** (`GenerationSignals.quote_applicable = True`).
  Rows written before the field existed must still load. *CLAUDE.md rule 4.*
- **`services/web/lib/types/generated.ts`.** It is generated, so never hand-edit it.
  *`services/core-api/scripts/gen_typescript.py`.*
- **`db_table` names mirroring the spec DDL.** `infra/migrations/sql/` is written
  against those exact names.
- **`--import-mode=importlib`, and no `services/ai-engine/tests/__init__.py`.** A
  whole-workspace pytest run dies at collection without them. *Comment in the root
  `pyproject.toml`.*
- **Separate connect and read timeouts** (3s / 120s). Collapsed, an unreachable
  provider hangs for 120s, while a short read timeout reports a cold model load as
  "down". *Comments in `.env.example`; CLAUDE.md Gotchas.*
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
  reason, and a `KbAuthorityLog` row. Ingestion scripts take the same path. *ADR-0002;
  `KbArticle.set_auto_reply_allowed` in `apps/kb/models.py`;
  `apps/kb/tests/test_article_create.py`.*
- **The deny-by-default `_degraded_signals()` in `apps/tickets/utils/pipeline.py`**: every check failed,
  `kb_auto_reply_allowed=False`, `kb_risk_tier="high"`.
- **A chunk's titles go into its embedding input, never into `content`**
  (`ArticleIndexer.ingest`). A chunk from the middle of a page means nothing
  to the embedder without them, while `content` must stay the exact text the
  model may quote. *`test_load_demo_kb.py::test_a_new_title_re_embeds_an_unchanged_body`.*
- **`KbChunk.stored_section_title` is the one place a section title is cut**,
  for both `ingest` and `chunks_are_current`. Two spellings would make every
  reload see stale chunks and re-embed the whole KB.
- **`load_demo_kb` rebuilds every `authored_link` row at the end of a load.**
  A link resolves only to a page already loaded, so the per-article rebuild in
  `ingest` misses links to pages loaded after it.
- **`sync_active_from_source` runs only after a full load, touches only
  articles with a `source_url`, and reactivates only pages loaded this time.**
  A `--limit` load would deactivate everything it skipped, an API-created
  article was never in a snapshot, and a page skipped for a hash mismatch
  would come back with stale text. *`test_load_demo_kb.py::test_a_partial_load_deactivates_nothing`,
  `::test_an_article_created_through_the_api_is_never_deactivated_by_a_reload`,
  `::test_a_page_skipped_for_a_hash_mismatch_is_not_reactivated`.*
- **`rebuild_authored_links` deletes and inserts in one transaction.** A
  reader sees the old rows or the new ones, never half of each.
  *`test_link_associations.py::test_a_full_rebuild_replaces_the_source_and_leaves_other_sources_alone`.*
- **`link_scores` skips links out of the KB and to the article itself before
  numbering positions.** Counted, they would use up places the per-seed cap
  counts. *`test_link_associations.py::test_link_scores_follow_document_order_and_skip_self_and_out_of_kb_links`.*
- **`Clarifications.options` rounds the score gap before comparing it with
  `option_margin`.** In floating point 0.97 - 0.87 is just under 0.1 and
  0.8 - 0.7 just over, so a page exactly at the margin would be offered or
  not by accident. *`test_clarification.py::TestClarifyOptions::test_a_page_exactly_at_the_margin_is_offered`.*
- **`Clarifications.answer` masks before taking the row lock, then re-checks
  under it, and enqueues the re-run only after commit.** Masking calls the NER
  model, so it can't hold the lock; the re-check makes a double submit answer
  once; a worker enqueued earlier could read the ticket without the answer.
  *`test_clarification.py::TestAnswering::test_a_second_answer_is_refused`.*
- **`trust_signals` carries `clarifications_asked` into the policy signals.**
  Dropped, it reads 0 and the router asks the requester again on every run.
  *`test_trust_signals.py::test_the_questions_already_asked_reach_the_router`.*
- **`pool_size` is reported, never a trust feature or a router input.** A
  bigger cross-encoder batch is a cost, not evidence for an answer.
  *`test_router.py::test_pool_size_never_changes_the_branch`,
  `test_trust_scorer.py::test_pool_size_does_not_change_score`.*
- **`production.py`'s `DEV_ONLY_SECRETS` equals `.env.example`'s dev secrets.**
  If the template's dev value changed and the denylist didn't, production
  would accept the new public value. The test imports production with
  stand-in secrets, since CI's `.env` is the template.
  *`apps/core/tests/test_settings_env.py::test_productions_denylist_is_the_templates_dev_secrets`.*
- **No `decrypt()` call without a `PiiAccessLog` row** in the same transaction, with
  a mandatory non-empty reason. *CLAUDE.md "Current state".*
- **Idempotency key `{ticket_id}:{attempt}` plus `acks_late`.** A redelivered task
  must not send a second auto-reply. *The `tasks.py` and `utils/pipeline.py` module
  docstrings.*

## ai-engine

- **`TriageState` is frozen with `extra="forbid"`.** Without that, an in-place
  mutation is silently discarded. *`tests/test_state.py`.*
- **The `_reject_unknown_keys` adapter in `graph/build/builder.py`.** LangGraph drops unknown
  update keys silently, so a typo'd key would look like it worked.
  *`test_compiler.py::test_update_key_missing_from_the_schema_raises`.*
- **`input_schema=state_schema` pinned in `GraphBuilder.compile`.**
  *`test_state.py::test_node_annotation_does_not_override_the_graph_schema`.*
- **Outcome membership checked by identity (`is`), not `in`** (`BaseNode.produces`). A `StrEnum` from
  another node with the same value compares equal.
  *`test_compiler.py::test_equal_valued_outcome_from_another_enum_raises`.*
- **Validation-field defaults read "failed"**, and **every `ValidateNode` exit
  returns all six checks.** `emit_signals` must never report checks that nobody ran
  as passing, and a check an exit leaves out silently reads as failed (on a route
  proposal that lowers trust). *`test_state.py::test_missing_validation_reads_as_every_check_failed`;
  the whole-update assertions in `test_validate.py`, one per exit.*
- **Jev's rerank choice gates (ADR-0026).** `rerank_confidence` defaults to 0.0
  and `cited_is_rerank_choice` to False, so a run that never reported them
  cannot auto-reply. Jev choosing `none` is below the floor in ai-engine
  and, through `rerank_chose_none`, in the router, so the ticket is counted
  as `retrieval_below_floor`, not `schema_invalid`. A reply missing a
  passage's probability raises instead of scoring 0. Equal probabilities keep
  the cross-encoder's order (a stable sort), the only order among Jev's
  near-zero ranks. *`test_router.py::test_rerank_signals_left_at_their_defaults_never_auto_reply`,
  `test_router.py::test_jev_choosing_none_is_retrieval_floor_not_schema_invalid`,
  `test_providers.py::test_a_reply_missing_a_passages_probability_raises`,
  `test_rerank.py::test_equal_jev_scores_keep_the_cross_encoder_order`.*
- **No KB page means `(False, "high")` in `pipeline.trust_signals`, a literal,
  not a setting.** No configuration may turn a missing page into "auto-reply
  allowed". *`apps/tickets/tests/test_trust_signals.py::test_no_kb_page_denies_auto_reply`.*
- **`EmitSignalsNode` reads nothing outside the state.** It runs on every path
  and must not raise; the KB authority is core-api's own read (ADR-0002).
  *`test_emit_signals.py::test_signals_read_nothing_outside_the_state`.*
- **`Candidate` carries no score.** RRF is derived from rank, so nothing may
  threshold on it. *ADR-0005; `graph/nodes/retrieve/fusion.py` docstring.*
- **`RerankNode` sorts by Jev's score before truncating.**
  *`test_rerank.py::test_jev_orders_and_scores_keeping_the_cross_encoder_score`.*
- **Vector search orders by raw `cosine_distance`, not by `1 - distance`.** Only the
  raw form can use the HNSW index. *`test_db_queries.py`.*
- **`đ`/`Đ` special-cased in `LexicalShortlister._tokenize`.** NFD does not
  decompose them. *`tests/test_shortlister_diacritics.py`.*
- **`max_retries=0` and a single `complete()` attempt.** A failed call goes to HITL.
  *`test_llm_client.py::test_a_single_failure_raises_without_retrying`;
  `test_provider_selection.py` tests on "without … sdk retries".*
- **No provider fallback, and an unknown provider name raises at import.** The wrong
  calibration would otherwise look healthy. *`test_provider_selection.py`.*
- **Provider construction opens no socket.** Importing `graph/triage.py` has to work
  without a database. *`test_provider_selection.py::test_building_providers_opens_no_connections`.*
- **`_JSON_OBJECT` response_format on chat clients.** Without it the output turns to
  prose and the HITL rate climbs silently. *Its comment in
  `core/providers/clients.py`.*
- **An embedder or reranker failure raises and never returns empty.** An empty result
  reads as "the KB has nothing" rather than "the provider is down".
  *`test_retrieve.py::test_embedder_failure_propagates_rather_than_returning_empty_candidates`.*
- **`DeepSeekPiiDetector` calls its own chat model, never `ChatClient`.**
  `ChatClient`'s errors quote the model's reply, and NER's reply is the PII.
  *ADR-0019; `test_pii.py::test_deepseek_errors_and_tracebacks_never_carry_the_text_or_reply`.*
- **NER has its own provider setting (`NER_CLIENT_PROVIDER`).** Pointing the
  proposal or the draft at DeepSeek must never send raw ticket text there as a
  side effect. *ADR-0019; `test_pii.py::test_the_proposal_or_draft_on_deepseek_keeps_ner_local`.*
- **Retrieval and the candidate pool raise without a drafted answer.** Falling
  back to the ticket alone would quietly run the weaker pipeline. *ADR-0021
  decision 6; `test_retrieve.py::test_retrieval_without_a_draft_raises_rather_than_retrieving_on_the_ticket`,
  `test_candidate_pool.py::test_the_pool_without_a_draft_raises`.*
- **`AIRunResponse.prompt_version` is `settings.prompt_version`, not the
  request's field.** core-api never sets the field, so its stale default would
  label every run. *`test_main.py::test_a_run_is_labelled_with_the_prompt_that_ran`.*
- **`deepseek_model` refuses to build without `CLOUD_BASE_URL`.** Without a
  base URL the OpenAI SDK sends the key to OpenAI.
  *`test_provider_selection.py::test_deepseek_without_its_key_model_or_url_is_fatal`.*
- **Link expansion joins `kb_articles.is_active` on the target.** Dropped, it
  sends retired pages to the cross-encoder and nothing fails. *ADR-0018;
  `test_links.py::test_reads_one_source_active_targets_ranked_by_score_per_seed`.*
- **The entity-graph build fails whole, never partly.** A failed section
  exports nothing (a graph missing pages would look complete); a reply over
  the policy's bounds fails its section rather than being cut; an unusable
  reply is asked once more of the retry model, since temperature 0 replays
  the same broken reply. *`test_entity_graph_build.py::test_a_failed_section_exports_nothing_and_a_rerun_asks_only_for_it`,
  `::test_a_reply_over_the_pair_limit_fails_rather_than_being_cut`,
  `::test_an_unusable_reply_is_asked_once_more_of_the_retry_model`.*
- **The entity-graph build strips link targets and resolves against every KB
  page.** A URL in the prompt would copy the authored links instead of reading
  the prose; resolving a sample against itself drops real pointers.
  *`test_entity_graph_build.py::test_the_model_never_sees_a_link_target`,
  `::test_a_sampled_page_can_point_to_a_page_outside_the_sample`.*
- **The path-traversal check in `core/prompts` (`check_version`).**
  *`test_infer.py::test_invalid_prompt_version_is_rejected`.*
- **Only the tables `ai_engine_ro` is granted are declared in `core/db/tables.py`,
  and only the offline entity-graph build writes.** *ADR-0004, ADR-0025;
  `tests/test_db_tables.py`.*
