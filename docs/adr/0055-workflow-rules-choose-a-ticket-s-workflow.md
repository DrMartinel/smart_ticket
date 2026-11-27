# ADR-0055: Workflow rules choose a ticket's workflow at handoff

**Status:** Proposed (2026-11-28). The owner took every recommendation on
the open questions the same day (*Owner's answers*). Built 2026-11-28 as
the build plan sets out (*As built*).
**Date:** 2026-11-28
**Amends:** ADR-0049 part 3 (a category names the workflow its tickets enter):
the category's workflow becomes the fallback, after the rules
**Builds on:** ADR-0001 (code decides), ADR-0028 (the lifecycle engine;
moves only through it), ADR-0043 (settings are data a workflow admin
changes live), ADR-0045 (URN permissions), ADR-0049 (categories as rows)
**Touches:** core-api `apps/lifecycle` (a model, a pure selector in
`domain/`, `services/engine.py`, routes), `apps/tickets/services/pipeline.py`,
`apps/review/services/decisions.py`, `apps/accounts/domain/data.py`
(no new permission, see decision 6), admin-console Admin › Settings ›
Workflows, the TS types

## Context

A ticket starts in the default workflow. At two handoffs it moves into
another one, chosen by its category alone (`engine.enter_category_workflow`,
`Category.workflow`):

- after an automatic route, at `auto_routed` (`pipeline.py`);
- after a review decision that hands it off, at `pending_review`
  (`review/services/decisions.py`).

So every network ticket takes the same path, whether it was a P1 routed
automatically or a P4 a reviewer corrected. A team that wants a separate path
for major tickets, or for tickets that came through review, can't have one:

- **Priority** is never read when the workflow is chosen. Transition rules
  and field events (`on_equals` and the rest) read only a workflow's custom
  fields, and `tickets.priority` is a column, so `change_workflow` can't fire
  on it either.
- **The branch** only decides whether the handoff happens (auto-route does,
  auto-reply doesn't), never which workflow follows.

The starting priority is already known at handoff: the SLA clocks start
there and set it when it is empty (`sla_clocks.start`: the person's choice,
else `initial_priority` with the customer's tier floor).

## Decision

1. **Workflow rules, as data.** A new table, `workflow_rules`: `order`
   (unique), and three keys, each null for "any":
   - `category`: a category slug;
   - `branch`: the branch of the ticket's latest routing decision
     (`auto_route` for an automatic route; `hitl`, `escalate`, `clarify` or
     `block` for a ticket a reviewer hands off);
   - `priority`: `P1`–`P4`;

   plus the `workflow` it chooses, `is_active`, and who changed it last with
   their reason. One value per key: a rule for P1 or P2 is two rows.
2. **The first active matching rule wins.** At each handoff, a pure function
   in `apps/lifecycle/domain/` (`select_workflow(rules, category, branch,
   priority)`) takes the active rules in `order`, and returns the first
   whose every non-null key equals the ticket's. No match falls back to the
   category's workflow, then the default: with no rules, behaviour is exactly
   today's. The function does no I/O; the engine fetches the rules and the
   ticket's values before the call, as `router.py` does.
3. **Chosen once, at handoff.** The selection runs at the same two handoffs
   as today, after the SLA clocks have set the starting priority, with the
   same guards (the ticket is still at a handoff status, no move is
   running). A later change of category or priority does not move a ticket
   that is already in a workflow: a person moves it, or a workflow's own
   `change_workflow` action does.
4. **Every selection is recorded.** The transfer's audit row gains
   `selected_by`: the rule's id, `category` or `default`. A failure in the
   selection or the move is skipped and audited as today
   (`CategoryWorkflowSkip.ERROR`): the ticket stays where it is, already
   handed to a team, and a person sees it.
5. **The checks from part 3 cover rules.** A rule can't name a strict
   workflow with no way out of `auto_routed`, `pending_review`, `escalated`
   or `reopened` (`workflow_has_no_way_out`). A rule may name the default
   workflow, which keeps matching tickets out of their category's workflow.
   A workflow a rule names can't be deleted (`workflow_in_use` names the
   rules too). A rule naming an inactive category is refused.
6. **Who may change them: `workflows:manage`, with a reason.** Rules choose
   a path through work, like the workflows themselves, so the workflow admin
   (and the manager) edits them, live at once (ADR-0043). No new permission.
   Each create, edit, reorder and delete writes an audit row with its reason.
7. **A preview route.** `GET /api/lifecycle/workflow-rules/preview` with a
   category, branch and priority answers which rule (or fallback) would
   choose which workflow, so a rule can be checked before it is turned on.

## How the earlier decisions still hold

- **Code decides.** No model reads or proposes a workflow; the router is
  unchanged and still pure. The rule keys are values code already set: the
  router's branch, the category the router or a person chose, and the
  priority the SLA code or a person chose.
- **Moves only through the engine (ADR-0028).** The move is the same
  `record_system_transfer`, at the same points, with the same guards.
- **ADR-0049 part 3.** The category's workflow stays, as the fallback; a
  category that names none still means the default.

## Consequences

- A workflow admin can give P1 network tickets their own path, or send every
  reviewed ticket through an intake workflow, without code.
- Order matters, and two rules can overlap; the preview and the list's order
  are how an admin sees which wins.
- Auto-replied tickets still enter no workflow: they never reach a handoff.
  A held-back auto-reply or auto-route does reach one, through review; it
  matches as `hitl`, the path it took (*As built*).
- A priority raised after handoff (by a person, or by an incident link) does
  not change the path. If teams need that, a later decision can add
  re-selection on a priority change (open question 1).

## Build plan

One PR (phase-2 work gets one PR each), one commit per step.

1. **The rule and the selector:** model `WorkflowRule` (`BaseModel`, UUID,
   `db_table = "workflow_rules"`) and its migration; `select_workflow` in
   `apps/lifecycle/domain/selection.py`. Tests, no DB: first match wins, null
   matches any, inactive rules skipped, no rules gives the category's
   workflow, no category workflow gives the default.
2. **The engine:** `enter_category_workflow` becomes `enter_handoff_workflow`
   (category, branch, priority), called at both handoffs; `selected_by` on
   the audit row. Tests: each handoff picks by rule; the priority the clocks
   set at handoff is the one matched; a failing selection is skipped and
   audited and the ticket keeps its team; a ticket already moved on is not
   moved.
3. **Routes:** list, create, edit, reorder, delete and preview under
   `/api/lifecycle/workflow-rules`, `require(Permission.WORKFLOWS_MANAGE)`
   to change and `WORKFLOWS_READ` to read, `agent=AgentTier.NONE`, a reason
   on every change; the part 3 checks; `ADDED_SINCE_SNAPSHOT` in
   `test_access_equivalence.py`; regenerate the TS types. Tests for each
   refusal code.
4. **Admin console:** Admin › Settings › Workflows gains "Which workflow": the
   ordered rules, add and edit with a reason, reorder, and the preview.
5. **Docs:** CLAUDE.md's "Where to make a change" row for the workflow a
   category's tickets enter, ADR-0049 part 3's pointer to this ADR,
   `docs/status.md` and `docs/TODO.md`.

## As built (2026-11-28)

- **The rule.** `WorkflowRule` (`workflow_rules`): `order` unique and
  deferred, so a reorder rewrites every row in one transaction; `category`
  references `ticket_categories.slug` like every other category column;
  `branch` and `priority` are text; `workflow` is protected from deletion.
- **The selector.** `select_workflow` in `apps/lifecycle/domain/selection.py`
  returns the workflow and `selected_by`. It also takes `include_inactive`,
  for the preview only.
- **The engine.** `enter_handoff_workflow(ticket, category, actor=…)` reads
  the branch of the ticket's latest `routing_decisions` row
  (`RoutingDecision.handed_off_as()`: `hitl` for an automatic route or reply
  that was held back, ADR-0051, since a reviewer handled the ticket; a
  held-back `clarify` takes the same path as any other and keeps its branch) and the priority from
  the row it locks, so the priority is the one the SLA clocks set when the
  ticket entered the handoff status. A reviewer's category correction does
  not change that priority. A handoff with no category and no matching rule
  leaves the ticket where it is, as before (`selected_by` `current`). The
  engine and the preview share `Lifecycle.choose_workflow`. The
  status-change audit row carries `selected_by`, `branch`, `held_back` and
  `priority`; a skipped move is still `category_workflow_skipped`, with
  `selected_by` when the selection ran.
- **The routes.** `/api/lifecycle/workflow-rules`: `GET`, `POST`,
  `PATCH` and `DELETE /{rule_id}`, `POST /reorder`, `GET /preview`
  (`category`, `branch`, `priority`, `include_inactive`). Refusals:
  `reason_required`, `rule_not_found`, `workflow_not_found`,
  `workflow_has_no_way_out`, `unknown_category` (unknown or inactive),
  `branch_never_hands_off` (`auto_reply`) and `order_incomplete` (a reorder
  that doesn't name every rule once). Audit events: `workflow_rule_created`,
  `workflow_rule_changed`, `workflow_rule_deleted`,
  `workflow_rules_reordered`, each with the reason. A new rule goes last. An
  edit checks only the values it changes, so a rule whose category was
  deactivated, or whose workflow lost its way out, can still be turned off.
  The preview answers `current`, with no workflow, for no category and no
  matching rule.
- **The console.** Admin › Settings › Workflows › Which workflow.

## Open questions (answered)

| # | Question | Options | Recommendation |
|---|---|---|---|
| 1 | Does a later priority or category change move a ticket? | only at handoff · re-select on every change · re-select only while the ticket is in a backlog status | **Only at handoff.** A ticket that changes workflow mid-work drops custom fields a team has filled; a person can still move it |
| 2 | More keys? | category, branch, priority only · also customer tier · also team | **The three for now.** Tier already raises priority (the floor), so a priority rule covers most tier cases; a key is one column and a test to add later |
| 3 | Is a rule's priority one value or a range ("P2 or higher")? | one value per row · a minimum | **One value.** Explicit rows read plainly in the list; four priorities make at most four rows |
| 4 | Should a reopened ticket be selected again? | no · yes, at `reopened` | **No,** as today: reopening returns the ticket to its own workflow's path |

## Owner's answers (2026-11-28)

1. **A workflow is chosen only at handoff.** A later priority or category
   change never moves the ticket; a person, or a workflow's own
   `change_workflow` action, still can.
2. **Three keys: category, branch, priority.** No customer tier or team key
   for now.
3. **One priority per rule.** A rule for P1 or P2 is two rows.
4. **No new choice at reopen.**

## Alternatives considered

- **Priority as a custom field, so `change_workflow` can fire on it.** Two
  sources of truth for priority, and a second move right after the first.
- **A workflow per category and priority, as columns on the category.** It
  doesn't cover the branch, and it grows a column for every new key.
- **Let a model pick the workflow.** The path a ticket takes is a decision;
  ADR-0001 keeps decisions in code.
