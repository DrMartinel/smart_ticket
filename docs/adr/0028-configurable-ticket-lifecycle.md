# ADR-0028: Configurable ticket lifecycle

**Status:** Accepted (2026-10-17), the owner's decision
**Date:** 2026-10-15
**Builds on:** ADR-0001 (the LLM proposes, code decides), ADR-0011 (UUID keys)
**Source:** `sm-workos/documentation/TASK_LIFECYCLE_BACKEND_DESIGN.md` and
`TASK_LIFECYCLE_EXTRACTION.md`, a design for a task service, adapted here
to tickets

## Context

A ticket's `status` was a free string. The triage pipeline wrote eight values
(`new`, `awaiting_requester`, `pending_review`, `blocked`, `escalated`,
`auto_replied`, `auto_routed`, `reopened`), and nothing described what happened
after a person picked a ticket up. Support teams need their own stages ("in
progress", "waiting on vendor", "resolved"), gates on moving between them
("a resolution note is required to resolve"), and automation when a ticket
moves (assign a team, set an SLA, call a webhook, ask for approval).

The source design is for a task service with task types, projects and a
Socket.IO frontend. This repo has none of those. Its constraint is the one in
CLAUDE.md: the router's decision must not be overridden by anything quieter
than a person.

## Decision

**1. Workflows, statuses and transitions are data** (`apps/lifecycle`).
A `SystemStatus` is a global stage (`is_backlog`, `is_completed`). A `Workflow`
is a named set of `WorkflowStatus`es, each mapped to one system status, and of
`Transition`s between them. A transition carries `TransitionRule`s, which gate
it on the ticket's custom field values, and `WorkflowAction`s, which run when it is
taken. A status carries actions too; they run when a ticket enters it. A
workflow is `strict` (only modelled transitions) or `open` (any move). Every
ticket gets the default workflow when it's submitted.

**2. The pipeline's statuses are reserved in every workflow, and only the
pipeline enters them.** Each workflow holds one status per `PipelineStatus`,
keyed by that value. They can be renamed, recoloured and re-based, never
deleted. They carry no actions, and no transition leads into them. The pipeline
moves a ticket with `lifecycle.system_move`: recorded as a `Transfer` and
audited, with no rules and no actions, and it cancels any transfer in flight.
It never fails for a workflow reason, so a configured workflow can't block,
delay or redirect a routing decision. Rules, actions and the workflow's
transitions apply to the moves people make. A ticket at `new` or
`awaiting_requester` belongs to the pipeline or its requester, so no person
can move it from there, even with `force`.

**3. `Ticket.status` holds the current status's key**, which the engine writes
alongside `Ticket.workflow_status` (`Ticket.enter_status`). Every existing
reader of `status` keeps working. `resolved_at` is set when a ticket enters a
completed system stage and cleared when it leaves one.

**4. Every status change is a `Transfer`, and every action execution is an
`ActionRun`.** Runs are planned when the move is requested and snapshot their
parameters. `before` actions (blocking only: webhook, n8n, approval) run
before the status changes, and a failure keeps the ticket where it was. Status
`enter` actions and `after` actions run once the move is committed; their
failures don't revert it. Actions run on Celery. Retries are idempotent:
a succeeded run is never re-executed. A watchdog fails runs that stall.

**5. Rules and field events are Python, not JavaScript.** The source design
runs `codeExecute` JS in QuickJS so its frontend can evaluate the same rules.
This repo has no such frontend. The rule, event and action catalogs are code
(`RuleCode`, `EventCode`, `ActionCode`) with parameter schemas, served by
`GET /api/lifecycle/catalog`, and the configuration rows refer to them by
code. No user-supplied code runs anywhere.

**6. Actions only see masked text.** Templates (`{{ticket.subject}}`) read
the masked subject and body, never the quarantine. A custom field value a
person types is masked like a clarification answer (`mask_reply`) before it
is stored. Webhooks go only to hosts on `LIFECYCLE_WEBHOOK_ALLOWED_HOSTS`, never
to link-local, multicast or unspecified addresses, and don't follow redirects.

**7. A failed transfer is listed for a person, with a `FailureCode`.**
`GET /api/lifecycle/transfers/failed` is that queue, and `POST
/api/lifecycle/tickets/{id}/retry` re-runs what failed. These failures are
not routing decisions, so they don't use `ReasonCode` and don't create
review items (a review item's override becomes an eval candidate).

## Not adopted from the source design

- **Socket.IO events.** This stack has no Socket.IO server. Clients read
  `waiting_transform` and the transfer log instead.
- **QuickJS and JS `codeExecute`** (Decision 5).
- **Task-only actions**: subtasks, parent tasks, projects, departments,
  comments, in-app notifications and Telegram.
- **NestJS-style operation ids and the generated client's paths.** The API
  follows this repo (`/api/lifecycle/...`, snake_case, UUIDs).

## Consequences

- Tunables are in `thresholds.yaml` (`lifecycle:`), and the HTTP timeouts,
  callback window, retry backoff and watchdog interval are in `.env.example`.
- Changing a ticket's stage after triage is now an API call that can be
  refused (`TRANSITION_NOT_ALLOWED`, `RULE_VIOLATION`) or queued
  (`waiting_transform`).
- `test_pipeline_statuses_are_written_only_by_the_lifecycle` fails if any
  other code assigns `ticket.status`.

## Amended 2026-10-15: hardening after a live probe

A live edge-case run found gaps; each now has a regression test in
`apps/lifecycle/tests/test_hardening.py`.

- **A `user` field holds an active username**, never free text, so nothing a
  person types reaches the database unmasked.
- **Webhook and n8n bodies are JSON templates**: placeholders fill only inside
  string values, so ticket text can't add keys. A body that isn't JSON (a bare
  placeholder) is refused when saved.
- **`pattern` rules match with a timeout** (`LIFECYCLE_RULE_PATTERN_TIMEOUT_SEC`,
  the `regex` module): a catastrophic expression counts as a broken rule
  instead of holding the ticket lock.
- **Every lock is taken ticket first**, then transfer, run, approval: retries
  and workers no longer deadlock.
- **A transition's rules are checked again at commit**, so a value changed
  while a move waited on an approval or webhook can't slip through.
- **Retry only restarts failed or stalled work.** A run still waiting for an
  answer refuses retry, and a callback token is valid for one attempt only.
- **`resolved_at` follows a stage change**: re-basing a status, or marking a
  system status completed, restamps the tickets in it. A pipeline status keeps
  whether it counts as resolved (`auto_replied` does, the rest don't).
- **A moved or cancelled run is never overwritten** by a worker finishing late.
- **Actions are checked when saved**:
  - placeholders must name real variables or fields
  - URLs must be on the allow-list
  - users must exist with a staff role (approvers: technician, manager or
    security)
  - email addresses must be valid, with a one-line subject
  - a `set_field` value must fit the field's type
- **Approvals.** Nobody approves their own move, and an expired approval
  can't be approved.
- **References.** A status, field or workflow that an action names can't be
  deleted or renamed.
- **Names are unique ignoring case and surrounding spaces.** Status keys fold
  `đ` to `d` and always fit `Ticket.status`.
- **Crafted input is a 4xx, never a 500.** This covers unknown ids, `null` in
  a PATCH, NaN or huge numbers, NUL bytes, and uniqueness races.
- **`change_workflow` refuses the ticket's own workflow**: that would be a move
  without its transition, rules and approvals.
