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
- **`lib/types/generated.ts` in `services/admin-console` and `services/chat`.** It is generated, so never hand-edit it.
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
- **`PiiReveal.read_logged` inserts the access-log row before it decrypts**, inside
  the reveal's transaction. Decrypting first looks equivalent. Then a failed insert
  leaves plaintext already in memory on a path that can return it.
  *`test_no_plaintext_when_access_log_insert_fails`, `test_decrypt_has_one_caller`.*
- **`PiiReveal.check_rate` inside the reveal's transaction, under a per-actor
  advisory lock.** Counting before the transaction looks the same. Then parallel
  requests all see the same count and a script gets past the hourly limit.
- **`placeholder_level` answering critical for an unknown label.** Defaulting to
  routine looks harmless today. A new credential label would then be revealable
  by technicians, with no error (hard rule 3). *`TestPlaceholderLevel`.*
- **The `pii_access_log` trigger** (`infra/migrations/sql/0007`). The REVOKE beside
  it does nothing to core-api's own role, which owns the table; only the trigger
  stops an UPDATE or DELETE. *`test_access_log_rejects_update_and_delete`.*
- **The reveal reason masked by the regex tier only** (`mask_regex_tier`), not NER.
  Going through `mask_reply` would make every reveal depend on ai-engine being up
  (BR-F5-04).
- **Idempotency key `{ticket_id}:{attempt}` plus `acks_late`.** A redelivered task
  must not send a second auto-reply. *The `tasks.py` and `utils/pipeline.py` module
  docstrings.*

### Ticket lifecycle (ADR-0028)

- **`lifecycle.system_move` for every pipeline status write.** Setting
  `ticket.status = "pending_review"` directly looks simpler. It would leave
  `workflow_status` behind and a move in flight running, and it would skip the
  transfer record and audit. *`apps/lifecycle/tests/test_pipeline.py`
  (`test_pipeline_statuses_are_written_only_by_the_lifecycle`).*
- **`system_move` never refuses.** No rule, transition, version or open
  transfer can stop it: it cancels what is in flight and recreates a missing
  pipeline status. A workflow that could refuse the pipeline would leave a
  ticket at `new`, invisible to every queue. *`test_a_pipeline_move_cancels_a_move_in_flight`,
  `test_a_pipeline_status_missing_from_a_workflow_is_recreated`, `test_a_workflows_rules_never_stop_a_reopen`.*
- **Pipeline statuses as targets only of the pipeline, and `new` /
  `awaiting_requester` as unmovable by people, even with `force`.** Otherwise
  a workflow action or a person could put a ticket at `auto_replied` without
  a routing decision, or take one from the requester mid-question.
  *`test_resolver.py` (`test_nobody_but_the_pipeline_moves_a_ticket_into_a_pipeline_status`,
  `test_a_ticket_in_triage_cannot_be_moved_even_by_force`).*
- **`Ticket.status` holding a status key beside `workflow_status`.** It
  duplicates the FK, but chat, the SQL index and every older reader key off
  the string. `Ticket.enter_status` is its only writer.
- **Webhook 5xx retried, 4xx aborting.** A server error is not the gate
  saying no; aborting on it would refuse moves whenever the hook is flaky.
  *`test_a_transient_failure_is_retried_with_backoff_then_fails`.*
- **The callback token includes the run's attempt.** A late callback from an
  earlier attempt can't finish a retried run. *`callback_token` in `actions.py`.*
- **`select_for_update(of=("self",))` in `Lifecycle.commit`.** Without `of`,
  Postgres refuses `FOR UPDATE` on the outer join `select_related` adds.

- **`Lifecycle.lock` taking the ticket before the transfer**, and `lock_run`
  taking the ticket before the run. Locking in any other order deadlocks
  against retries, which lock the ticket first.
- **`commit` re-checking the transition's rules.** A field can change while a
  move waits on its `before` actions.
- **`ActionRunner.finish` writing only while the run is `running`.** A
  pipeline move can cancel a run mid-flight; an unconditional save would mark
  it succeeded. *`test_a_run_cancelled_mid_flight_is_not_marked_succeeded`.*
- **`render_json` for webhook and n8n bodies.** Filling placeholders in the raw
  text lets ticket text add JSON keys. *`test_a_placeholder_cannot_add_keys_to_a_webhook_body`.*
- **The `regex` module's `timeout=` in the `pattern` rule.** Plain `re` has no
  timeout, and a catastrophic pattern would hang a request holding the ticket lock.
- **`Workflow.objects.default()` reseeding a missing default.** Submission
  calls it; without the reseed a flushed or damaged table stops every ticket.

### Sign-in (ADR-0029)

- **`SessionAuth` checking the token's `sid` against a live family.** It looks
  like an extra query per request. Without it, signing out leaves the access
  token working until it expires. *`apps/accounts/tests/test_sessions.py`.*
- **The access token kept in memory, not `localStorage`.** Storage is readable
  by any script on the page; memory dies with it. A reload costs one refresh.
- **The reuse grace window** (`AUTH_REFRESH_REUSE_GRACE_SEC`). Without it two
  tabs refreshing together look like theft and sign the user out.
- **`X-Auth-Client` on the cookie endpoints.** It picks the cookie, and as a
  custom header it forces a CORS preflight on cross-origin calls.
- **Refresh tokens stored as SHA-256 hashes.** A database read must not yield
  usable tokens.

### Sign-in through Keycloak (F13)

- **One answer for every failed local sign-in**, and a password hash even for an
  unknown name (`User().set_password`). Distinct codes or a faster reply would
  tell a caller which names are break-glass accounts, the ones worth attacking.
  *`test_local_login_refuses_everyone_alike`.*
- **`Identities.link` refusing break-glass, inactive and ambiguous matches.**
  Linking by email looks like a convenience. A linked break-glass account joins
  the sync, which deactivates it exactly when Keycloak breaks.
  *`TestLinking`.*
- **`OIDC_MIN_REFETCH_SEC` on unknown key ids and the sign-in page.** Without it
  each unauthenticated request with a random `kid` is one call to Keycloak.
- **The sync reading everyone before changing anyone.** Changing users as they
  are read would deactivate half the company on a Keycloak hiccup (BR-F13-08).

### Notifications (F4, ADR-0033)

- **`Notifier.emit` writing in the caller's transaction and sending only
  `on_commit`.** Sending inline looks simpler. A rolled-back assignment would
  then have mailed its assignee, and a slow relay would hold the ticket's row
  lock. *`test_rolled_back_event_sends_nothing`.*
- **`emit` catching every exception in its own savepoint** and auditing
  `notification_emit_failed`. A notice must never undo the event it reports
  (BR-X-07): without the catch, a broken matrix row would fail every assignment.
  *`test_an_emit_that_crashes_is_audited_and_the_event_goes_on`.*
- **The unique key on `(event_id, user, subscription, channel)` with
  `nulls_distinct=False`.** With Postgres's default, a user message's null
  `subscription` makes every row distinct and a re-emit sends twice (BR-F4-08).
  *`test_a_re_emitted_event_never_double_sends`.*
- **`Dispatcher.claim` locking the row (`skip_locked`, `of=self`) and moving it
  to `sending` before the send.** The on-commit dispatch and the sweep can both
  pick a message; only the claim makes it one send. *`test_dispatch_twice_sends_once`.*
- **Mandatory cells read from the catalog, never from `notif_matrix_rules.mandatory`.**
  The column is a display copy; trusting it lets a database edit silence
  security alerts. *`test_mandatory_cell_ignores_preference`.*
- **Webhook secrets under `NOTIFICATION_SECRET_KEY`, not the PII key.** One
  key would give the PII key a second reader, which F5 forbids.
  *`test_decrypt_has_one_caller`.*

### Teams and assignment (F2)

- **`pg_advisory_xact_lock('assign:' || team_id)` before picking a person.**
  Two handoffs at once would read the same loads and give both tickets to the
  same member (BR-F2-08). *`test_concurrent_assignments_balance` fails without it.*
- **`assign_after_handoff` running in its own savepoint and catching every error.**
  It runs inside the pipeline's transaction right after the status move; an
  exception there would undo the routing outcome (BR-F2-02, BR-X-07).
  *`test_an_assignment_error_keeps_the_status_and_is_audited`.*
- **Take checking `expected_version` and raising `tickets.version`.** Two people
  clicking Take on the same row both see an unowned ticket; only the version
  makes the second one a 409 `already_assigned`. *`test_two_takes_one_winner`.*
- **The approval category never comes from `proposed_*`.** The fallback chain is
  the reviewer's correction, the router's category, then the category the
  reviewer confirmed (Jev's signal). Reading the proposal would let the LLM pick
  the team (ADR-0001).

### SLA clocks (F1, ADR-0030)

- **`SlaClocks.guarded` wrapping every clock change in a savepoint and catching
  every error.** The hook runs inside `system_move`, which must never fail for a
  workflow reason (ADR-0028 §2). *`test_system_move_succeeds_when_sla_hook_raises`.*
- **`policy_snapshot` on each clock.** Reading the live policy would move every
  running ticket's due time when someone edits a target (BR-F1-05).
  *`test_policy_edit_does_not_change_running_clock`.*
- **The `warned_at` / `breached_at` / `escalated_at` null checks under
  `skip_locked`, and notice ids from ticket, kind, start and level.** Without
  both, overlapping sweeps or a rebuild send the same breach again.
  *`test_each_sla_level_fires_once`, `test_a_rebuild_does_not_send_a_breach_again`.*
- **`recompute` keeping a due time that has already passed.** Recomputing past the
  target would otherwise stamp "due now" over the real breach time.
  *`test_a_rebuild_keeps_the_time_a_clock_fell_due`.*

### Requester chat and comments (F3, ADR-0034)

- **Prior turns built only from decided turns, re-checked for a block or a
  mask failure on every build.** A turn still at `new` hasn't passed the
  injection check, and a blocked turn decided after the next question was
  asked must still never become context.
  *`test_an_undecided_turn_is_never_context`,
  `test_a_blocked_turn_is_never_context_even_if_the_conversation_stayed_open`.*
- **The `reporter_id` filter beside `conversation` in `prior_turns`.** A forged
  or misattached ticket in the conversation would otherwise reach the model.
  *`test_prior_turns_only_from_same_conversation_and_requester`.*
- **`context_for` catching every error and analysing the ticket alone.** The
  context is an extra; a failure building it must never keep the ticket from
  a decision (ADR-0034, BR-X-07). *`test_a_failure_building_context_analyses_the_ticket_alone`.*
- **Only `draft_answer`, `infer` and `graph/ticket.py` read `prior_turns` in
  ai-engine.** Anywhere else it could become a signal or a score.
  *ai-engine `test_only_the_draft_and_the_proposal_read_earlier_turns`.*
- **`hidden_for_review` and the comment's review item.** A comment whose NER
  failed carries only the regex tier's masking; staff must not read it until a
  person checks it, exactly as a `mask_failed` ticket. *`test_reply_mask_failed_hidden_and_queued`.*
- **The placeholder-collision retry in `Comments.add`.** Two comments masked at
  once would both take `[EMAIL_n]`, and the second would overwrite the first's
  quarantine reference in `pii_map`.
- **`reopen_now` refusing an open ticket.** The old `reopen_ticket` reopened
  anything, which would inflate K7 (`reopen_rate_after_autoreply`).
  *`test_the_reopen_task_refuses_an_open_ticket`.*

### Security inbox (F8)

- **`SecurityAlerts.raise_` as the only writer of `security_alert` audit rows.**
  An event written straight to the audit log is seen by nobody.
  *`test_every_security_alert_audit_raises_an_alert`.*
- **The advisory lock and `select_for_update` around grouping.** Two raises at
  once would each create an alert and page security twice. *`test_repeat_alerts_group`.*
- **`ack_overdue_notified_at` set by a conditional update.** Overlapping sweeps
  would page again. *`test_overdue_acknowledgement_is_escalated_once`.*
- **Release moving the ticket with `system_move` and a new review item, never
  `process_ticket`.** Re-running the AI would block it again.
  *`test_release_goes_to_a_person_not_the_ai`.*
- **`SECURITY_QUEUES` excluded from handoff in `ReviewDecisions.decide`.**
  Otherwise agreeing with a block assigns a blocked ticket to a team.
  *`test_a_true_positive_keeps_the_ticket_blocked_and_assigns_nobody`.*

### Rollout and thresholds (F9, ADR-0035)

- **`Rollout.is_live` read in `_finalize`, never in `router.py`.** The flag
  decides whether a decision is carried out, never which it is; replays depend
  on the router staying pure. *`test_route_is_identical_whatever_the_flags`.*
- **Two keys, either missing is shadow** (ADR-0044 dropped the thresholds
  key). *`test_env_shadow_overrides_flags`.*
- **No `runbook` member in `FlagBranch`** (ADR-0006). *`test_no_runbook_flag_exists`.*

### Mass incidents (F7)

- **One advisory lock (`mass_incident`) for matching and detection, with no
  category in the key.** The category is unknown at detection; keying on it
  merged every incident into `other`. *`test_unrelated_outages_get_separate_incidents`.*
- **The detector leaving out the ticket itself and linked tickets, and
  `ticket_count` recounted from `incident_links`.** The ticket's embedding is
  stored before detection, so it counted twice.
  *`test_ticket_count_counts_each_ticket_once`, `test_ticket_count_comes_from_the_links`.*
- **`Incidents.agree` deciding with `handoff=False`.** Confirming agrees with
  the router; a hand-off would assign forty tickets to a team, and an
  eval candidate would teach the eval set from agreement.
  *`test_confirm_approves_without_eval_candidates`.*
- **`attach` skipping the review item only when not in shadow mode.** In shadow
  mode a person still sees every ticket.
  *`test_in_shadow_mode_a_late_joiner_still_reaches_a_reviewer`.*
- **`mask_text` raising on `mask_failed`.** A broadcast reaches every linked
  requester; a failed mask must send nothing. *`test_a_masking_failure_sends_nothing`.*
- **Close-all catching `LifecycleError` per ticket.** One refused move must not
  stop the rest. *`test_close_all_continues_after_refusal`.*

### KB governance (F6, ADR-0036)

- **Drafts in their own table, with no grant to `ai_engine_ro`.** A status on
  `kb_articles` would need a filter in every ai-engine query; one forgotten
  filter puts unreviewed text in front of the model.
  *`test_draft_invisible_to_ai_engine_queries`.*
- **`KbDrafts.publish` revoking in the approve transaction, and never
  granting.** Split from the page write, a crash leaves new text under the old
  approval. *`test_edit_revokes_authority_with_log_row`, `test_publish_never_grants_authority`.*
- **`_kb_meta` reading `is_authorized()`, not `auto_reply_allowed`.** Text
  changed outside a draft (a reload, a SQL fix) would otherwise keep its
  approval silently. *`test_hash_mismatch_means_not_authorized`.*
- **`TextSha256` hashing exactly `title + "\n" + body` as UTF-8, like
  `text_sha256`.** If the two drift, every page reads as not authorized in the
  F9 gate count and nothing fails. *`test_the_database_hash_matches_the_python_hash`.*
- **Conflicts compared by the text hash, not `version`.** A grant bumps the
  version, so a version check makes every open draft a conflict.
  *`test_a_grant_alone_is_not_a_conflict`.*
- **`KbAuthority.bulk` checking every page before changing any.** A partial
  bulk grant would approve the low-risk half of a request that had to be
  refused. *`test_bulk_refuses_high_risk`.*
- **`KbDrafts.ingest` running `indexer.ingest` inside `transaction.atomic`.**
  `ingest` deletes the chunks first; outside a transaction a failed embed
  leaves the page with none. *`test_a_failed_ingest_keeps_the_old_chunks`.*
- **`KbGaps.build` deleting only open clusters on a re-run.** Deleting the
  report would cascade to a dismissed topic and bring it back next week.
  *`test_a_dismissed_topic_is_hidden_from_later_reports`.*

### Reporting (F10)

- **SLA % from stopped clocks only (`TicketFactsQuerySet.stopped`), never
  `sla_due_at`.** `sla_due_at` is wall-clock and written only by `set_sla`;
  a running or cancelled clock in the denominator changes last month's number
  every night. *`test_sla_compliance_uses_clocks_not_sla_due_at`,
  `test_an_open_breached_clock_is_only_open_overdue`.*
- **`linked_incident` rows left out of every SLA %.** Their clocks were paused
  by design; counting them makes a mass incident look like a team failing.
  *`test_incident_tickets_excluded_from_team_sla`.*
- **`automation_rate_live` and `_would_have` as separate fields, labelled
  "not a target".** One number counts shadow decisions as automation that
  never happened (ADR-0006). *`test_automation_rate_split_live_vs_shadow`.*
- **The rollout report calling `rollout_metrics.shadow_agreement` over
  `reports.rollout_days`.** A second query or window would show a manager a
  different number than the gate approves on.
  *`test_ac_f10_10_shadow_agreement_uses_the_gate_query`.*
- **`Reports.team_scope` / `reviewers` refusing instead of filtering
  silently.** Per-person rows are need-to-know (BR-F10-05).
  *`test_lead_cannot_read_other_team`, `test_ac_f10_04_a_reviewer_sees_only_themself`.*
- **The weekly email's event id derived from the ISO week.** A beat retry
  would otherwise email every manager twice. *`test_the_weekly_email_goes_once_per_week`.*

### Role enforcement (PRE-1)

- **A `require(Permission…)` gate on every route, even signed-in-only ones** (once `require_role` with `ALL_ROLES`).
  It looks redundant next to `SessionAuth`. Without it,
  `test_every_route_is_gated` can't tell a route someone forgot from one
  that is meant for everyone. *`apps/accounts/tests/test_role_enforcement.py`.*
- **The `__signature__` `require_role` sets, with annotations evaluated.**
  Ninja evaluates string annotations in `call.__globals__`, which for the
  wrapper is `permissions.py`. In a module with `from __future__ import
  annotations` every request body then fails to resolve, and each call is a
  500. *The chat and review API tests.*
- **`gate_authentication` wrapping each gated route's auth callback** (`GatedAuth`,
  called in `config/urls.py`). The check inside the handler looks like enough.
  Without the auth-layer one, Ninja validates the body first: a refused caller
  with a malformed body gets a 422 listing the schema and no `access_denied`
  row. *`test_a_refused_caller_is_refused_before_the_body_is_read`.*
- **`gate_of` following `__wrapped__`.** `@paginate` sits above the
  gate on `GET /api/kb`; without the walk that route reads as ungated.
- **The runbook checks in `RunbookExecution.objects.execute`**
  (`may_run_runbooks` for the approver and the executor) beside the route
  gates. Approvals recorded before PRE-1 had no role check; the model
  check refuses them however execution is reached (ADR-0006).

### People, departments and access (F14, ADR-0045)

- **Locked permissions** (`PermissionSpec.locked`) that a custom role can
  never hold. Without them a custom role is a quiet path to KB authority,
  PII reveal or access admin that no route gate notices.
  *`test_every_locked_permission_is_refused_on_a_custom_role`.*
- **`ADDED_SINCE_SNAPSHOT` and the route snapshot** in
  `test_access_equivalence.py`. They look like bookkeeping. They are the only
  proof the move from roles to permissions changed nobody's access: a new
  route must be listed with its permission, and every old route must admit
  the same people as before.
- **System roles grantable by `access:grant` holders, custom roles only by
  holders of each permission** (`Grants.check_grantable`). Making system
  roles follow the custom rule stops a manager giving the ADR-0042 add-ons;
  making custom roles follow the system rule lets a manager build one with
  anything they lack.
- **`Grants.changed` ending the person's sessions.** `Access.of` is cached on
  the user object for the request; without the revoke, a grant ended now
  still applies until the session's token expires.
- **The grantee excluded at every step of `AccessReviews.reviewer`,** with
  `no_other_reviewer` when nobody else can answer. Falling back to the
  opener alone hands an access admin their own grant to keep.
- **`People.set_status` writing through a queryset `.update()`.**
  `test_pipeline_statuses_are_written_only_by_the_lifecycle` reads any
  `x.status =` as a ticket status write.
- **`test_services_check_permissions_not_role_names`** and its short
  allowlist. A service that tests `user.role == "manager"` again quietly
  ignores custom roles and scoped grants: a custom role holding the
  permission is refused, and a manager whose grant was ended keeps the rule.
- **`delegated=True` going through `check_delegated` *and then* the
  hold-each-permission check.** Skipping the second lets a head hand out
  a delegable role holding permissions the head lacks in that subtree;
  skipping the first lets a head grant system roles or anyone outside
  their subtree.
- **`WITHDRAWN_SINCE_SNAPSHOT`** in `test_access_equivalence.py`: routes the
  snapshot had that are gone on purpose (`PUT …/rights`). Without it the
  equivalence test either fails or gets its snapshot edited, which hides
  the next accidental removal.
- **`tickets.requester_department` set at submit,** not read through the
  reporter later. A person moved to another department would otherwise
  carry their old tickets into their new head's reports.
- **`select_for_update(of=("self",))`** in `Grants.locked` and
  `People.release_tickets`: Postgres refuses a row lock across the nullable
  joins `select_related` adds.

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
- **`mask_guard` between the injection guard and `draft_answer`.** A
  `mask_failed` ticket's text was masked by the regex tier only, so it may
  still hold free-form PII; the guard sends it straight to `emit_signals`,
  and no hosted model (DeepSeek's draft and proposal, Jev, the cross-encoder)
  sees it. Before it, the router's `PII_MASK_FAILED` gate ran only after the
  whole graph, so every such ticket went to DeepSeek and Jev first (found
  2026-11-02 on TKT-2026-001300 to 001302). It sits after `injection` so a
  mask-failed ticket with an injection is still blocked with a security
  alert. *`test_mask_guard.py::test_a_mask_failed_ticket_reaches_no_model`,
  `::test_a_mask_failed_ticket_with_an_injection_is_still_flagged`,
  `test_build.py::test_safety_critical_routes`.*
- **Validation-field defaults read "failed"**, and **every `ValidateNode` exit
  returns all six checks.** `emit_signals` must never report checks that nobody ran
  as passing, and a check an exit leaves out silently reads as failed (on a route
  proposal that lowers trust). *`test_state.py::test_missing_validation_reads_as_every_check_failed`;
  the whole-update assertions in `test_validate.py`, one per exit.*
- **The floor reads Jev's passages' total, and the buttons read Jev's
  per-page yes/no scores (ADR-0026, ADR-0023 amended 2026-10-14).** On the
  choice scale the top-1 drops when a ticket is ambiguous, and one passage
  takes almost all the probability, so neither the old floor nor the old
  button rule works on it. `rerank_total` defaults to 0.0 (below the floor)
  and a chunk with no `option_score` offers no button. *`test_router.py::test_a_total_left_at_its_default_is_below_the_floor`,
  `test_classify_category.py::test_a_split_choice_with_a_high_total_reaches_the_llm`,
  `test_clarification.py::TestClarifyOptions::test_chunks_jev_did_not_score_offer_nothing`,
  `test_score_options.py::test_a_jev_failure_while_scoring_options_propagates`.*
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

### Entity graph as a KB feature (F11, ADR-0037)

- **`ArticleIndexer.ingest` marking `entity_graph` edges stale instead of
  deleting them.** Deleting drops the page out of link expansion until a
  manual build; an old pointer to a live fix page is better than none.
  *`test_ingest_marks_edges_stale_not_deleted`.*
- **`upsert_from_source` passing `graph_rebuild=None`.** A snapshot load
  would otherwise file one request per page, and the next `--pending` run
  re-extracts the whole KB through DeepSeek.
  *`test_a_snapshot_reload_files_no_rebuild_request`.*
- **The link query dropping every overridden pair from the built edges.**
  Without it an `add` over a built edge takes two of the seed's slots, and a
  `hide` is ignored. Overrides live in their own table, which no build
  writes, so they outlive rebuilds. *`test_an_overridden_pair_is_never_read_from_the_built_edges`,
  `test_hide_override_survives_rebuild`, `test_add_override_ranks_first`.*
- **`--pending` closing its requests in the same `db.write` as the edges.**
  Closed separately, a failure between the two leaves new edges with an
  open request (rebuilt again) or a `done` request with old edges.
  *`test_pending_rebuilds_only_requested_pages_and_closes_them`.*
- **Graph health counting only runs that report `origin`.** Older runs have
  none; counting them as fused understates the expansion share.
  *`test_the_expansion_share_counts_only_runs_that_report_origins`.*


### Runbook executors (F12, ADR-0038)

- **`Runbooks.start` returning None for any row past `queued`, under the row
  lock.** Celery may deliver a task twice; without it a grant or a restart
  runs twice. *`test_a_row_past_queued_is_never_sent_again`,
  `test_timeout_after_send_is_unknown_not_retried`.*
- **`Runbooks.why_not_runnable`, the worker's second look at ADR-0006 and the
  catalog.** A row queued by any other path, a decision deleted after the
  execute, or a catalog change after it (live at once since ADR-0043) would
  otherwise reach Keycloak.
  *`test_the_worker_refuses_a_run_whose_approval_disappeared`,
  `test_a_catalog_change_after_approval_stops_the_run`.*
- **`KeycloakAdmin.change` and `N8nExecutor.run` telling "never sent"
  (`failed`) from "sent, no answer" (`unknown`).** `OutboundNoAnswer` is the
  outbound client's half of it: a read timeout used to look like a connect
  failure, and a `failed` grant invites a person to grant again.
  *`test_an_unreachable_keycloak_is_failed`,
  `test_timeout_after_send_is_unknown_not_retried`,
  `test_n8n_without_an_answer_is_unknown`.*
- **The reporter rule checked on the approver's payload, not the draft's.**
  The LLM's target is a suggestion; the approver's edit is what runs, so
  that is what the rule must see. *`test_reset_targets_only_the_reporter`,
  `test_what_runs_is_what_the_approver_saw`.*
- **`ITSM_GRANTABLE_GROUP_PREFIXES` checked at the catalog and again at
  execute.** A runbook that could grant any group would let an approved
  ticket put someone in a group another system reads as rights. *`test_a_group_carrying_rights_is_never_grantable`.*
- **Catalog changes held in `pending_change`.** Writing them to the live
  fields would let a workflow admin change what an approved runbook does
  without a manager. *`test_a_catalog_change_needs_a_manager`.*
