# ADR-0049: Ticket categories are rows in `ticket_categories`

**Status:** Accepted for parts 1 and 2 (2026-11-26). Part 1 (decisions 1–4) is merged; part 2 (decision 5, the category set on the wire, open questions 1 and 2) is built and waits on its eval run. Part 3 (a workflow per category) is built as open question 3 proposes and waits on the owner's answer to it. Part 4 (the agent reads the categories, open question 4) is built. Open questions 1, 2 and 4 are answered; 3 and part of 2 are still open.
**Date:** 2026-11-26
**Builds on:** ADR-0017 (Jev chooses the category), ADR-0031 (teams own categories), ADR-0028 (workflows), ADR-0045 (permissions), ADR-0046 (agent tiers)
**Will amend:** ADR-0017, once part 2 builds Jev's category question from the rows

## Context

The six categories (`hardware`, `software`, `network`, `access`,
`security`, `other`) existed in three places that had to agree by hand:
the `TicketCategory` enum in both services, the criteria of
`category.v2.json`, and eight hardcoded lists in the admin console. Eleven
columns in ten tables stored a category as free text. Django `choices`,
which the database never checks, covered seven of them; nothing covered
the other four (`review_decisions.corrected_category`,
`team_reassignments.from_category` and `to_category`,
`report_ticket_facts.category`). Adding a category, or
designing a workflow per category, meant a code change in every one of
those places.

Teams and the categories they own were already data (`team_teams`,
`team_categories`, ADR-0031); the category set was not.

## Decision

1. **`ticket_categories` is the category set.** One row per category:
   `slug` (what every category column stores), `name`, `description` (what
   the classifier is told the category means), `is_active`, `is_security`,
   `is_routable`, `sort_order`, `version`. The seed copies each
   description verbatim from `category.v2.json`; a test fails if the two
   differ.
2. **The database enforces it.** Every column that stores a category
   (`tickets`, `incidents`, `kb_articles`, `kb_drafts`, `sla_policies`,
   `fewshot_examples`, `team_categories`, `review_decisions.corrected_category`,
   `team_reassignments.from_/to_category`, `report_ticket_facts`) has a
   foreign key on `ticket_categories(slug)`, `ON DELETE RESTRICT`
   (`infra/migrations/sql/0010`). A category is never deleted while used.
   The column names and stored values are unchanged. Before the database
   sees it, every service that writes a category from a request (incidents,
   KB pages and drafts, a reviewer's correction, a reassignment, a team's
   categories, an SLA policy) refuses one that is unknown or inactive with
   422 `unknown_category` (`Category.objects.require`).
3. **Reads go through `GET /api/categories`** (`categories:read`; staff
   roles), and every console picker reads it. `PATCH /api/categories/{slug}`
   (`categories:manage`; manager, workflow admin) changes only `name` and
   `sort_order`, with a reason, audited `category_changed`, bumping
   `version`; any other field is refused with 422. Both routes are
   `AgentTier.NONE`.
4. **The description and flags change by pull request for now.** A
   description is classifier input, so editing it in the database would
   move the classifier without the eval gate. Until a reviewed change path
   exists (open question 1), the route refuses to touch them.
5. **`is_security` replaces the slug check** wherever code means "the
   security category" (router's `clarify_security`, `check_category_scope`,
   and the P2-for-security priority in `apps/sla/services/clocks.py`), in
   part 2. Part 1 only seeds the flag.
6. **Only active categories need an owner.** BR-F2-01 ("every category has
   exactly one owning team") now reads the active rows: an inactive
   category may have no team, and no team can claim one.

### Later parts

- **Part 2:** core-api sends the active categories (slug and description)
  in `AIRunRequest`; ai-engine builds Jev's choice question from them and
  `category.v3.json` (instructions only); `Router.route` takes the same
  snapshot as an argument and records it in `routing_decisions` beside
  `thresholds_used`. An empty or fallback-less set → HITL
  `category_set_invalid`; a routed ticket in a category with
  `is_routable=false` → HITL `category_not_routable`. The wire change lands
  in both services in one PR (hard rule 4) and needs an eval run.
  As built, see "Part 2 as built" below.
- **Part 3:** a category may name a workflow; a ticket moves into it at
  handoff. As built, see "Part 3 as built" below.
- **Part 4:** an agent-readable category route, once the F15 tier table
  names it. As built, see "Part 4 as built" below.

### Part 2 as built (2026-11-26)

- **The wire.** `AIRunRequest.categories` is the active rows' slug and
  description, in slug order, so the display order a person changes
  never reorders Jev's options. ai-engine refuses an empty list or a slug
  sent twice (422, so `ai_engine_unavailable`).
- **The question.** `category.v3.json` is `category.v2`'s instructions with
  no options; ai-engine adds one option per category sent. With the six
  seeded rows in v2's order the question is v2's byte for byte (a test
  pins it); core-api sends them in slug order, so the options' order is the
  one difference the eval run has to show is harmless. The instructions
  still name `access` by its slug.
- **An unusable set.** "Fallback-less" is read as "no security category":
  no row marks a fallback, and without an `is_security` row no ticket can be
  held as security. An empty set, a set with no security category, a
  category with a blank description (Jev would be told nothing about it;
  the database also refuses one), or Jev choosing outside the set is
  `category_set_invalid`. The router owns the rule, after the hard gates.
  The pipeline checks the set before calling ai-engine, records a degraded
  run (`degraded_reason` `category_set_invalid`) without calling it, and
  still asks the router, so a critical-PII ticket is blocked, a failed mask
  goes to its queue and an agent's hand-off keeps its reason.
- **The evals read the set once per run** from the database they run
  against, pass it to ai-engine and the router, and record its slugs,
  versions and flags with the results (`category_set`), so a run against
  an edited set can be told apart from one against the seed.
- **`is_routable`** gates `auto_route` only. An auto-reply takes its page's
  category, and its authority is the page's (ADR-0002).
- **`categories_used`** on each routing decision records each category's
  slug, version and flags, not its description: the description a decision
  ran against is the one at that version, and every change is a
  `category_changed` audit row with the old and new text.
- **A manager's edit** (open questions 1 and 2) needs
  `categories:define`, held by the manager role only and locked out of
  custom roles. A workflow admin still renames and reorders.
- **No enum.** `TicketCategory` is gone from both services; the request
  schemas take a slug (`CategorySlug`) and each service checks it is active.

### Part 3 as built (2026-11-26)

- **The switch.** `ticket_categories.workflow` is a nullable reference to
  a workflow; none means the default workflow. Anyone holding
  `categories:manage` (manager, workflow admin) sets or clears it, with a
  reason, on the Categories page (`PATCH /api/categories/{slug}` with
  `workflow_id`; null clears it, leaving it out keeps it). It chooses the
  path a ticket takes, not what Jev reads, so it does not need
  `categories:define`. The default workflow can't be named
  (`workflow_is_default`: none already means it), nor a strict workflow
  with no transition out of `auto_routed`, `pending_review`, `escalated`
  or `reopened` (`workflow_has_no_way_out`), where a handed-off or reopened
  ticket would be stuck. The check runs only when a category's workflow is
  set or changed: a later edit to the workflow's transitions, a switch from
  open to strict, or making it the default is not checked again, and an
  edit that sends the same workflow back is not refused for it. A workflow
  a category names can't be deleted (409 `workflow_in_use`, naming the
  categories).
- **When a ticket moves.** At handoff, before it is assigned: after an
  automatic route (at `auto_routed`), and after a review decision that
  hands the ticket off (at `pending_review`). The category is the one the
  ticket is handed off with: a reviewer's correction moves it into the
  corrected category's workflow, and a category the reviewer confirmed
  counts the same, and a category with no workflow returns the ticket to
  the default one. A handoff with no category leaves the ticket in the
  workflow it is in. In shadow mode the router's decision moves nothing; the
  ticket moves when a reviewer hands it off. An approved security-queue
  item, a reopen and a reassign leave the ticket's workflow as it is.
- **Where it lands.** Only a ticket at a handoff status (`auto_routed`,
  `pending_review`, `escalated`) moves, to the same status in the target
  workflow: every workflow has the pipeline statuses
  (`Lifecycle.pipeline_status` recreates a missing one). A ticket a person
  has already moved on stays where it is: a custom status with the same
  key in another workflow may pause SLA or wait on the requester
  differently. That, a move running, or a failure leaves the ticket where
  it is and audits `category_workflow_skipped` with the reason
  (`already_moved_on`, `a_move_is_running`, `error`). A failure never
  undoes the routing or review decision it follows.
- **What moves with it.** Field values of the same name and type, as the
  "Change workflow" action carries them; the rest are dropped and named in
  the status-change audit row. The move is a system move: no transition
  rules, no workflow actions, the same SLA and notice hooks as any status
  change.

### Part 4 as built (2026-11-26)

- **The route.** `GET /api/categories` is `AgentTier.READ`, named in the
  F15 tier table (06-F15 §h.3). Its edit route stays `none`: an agent
  acting for a manager is refused (`agent_not_allowed`).
- **The tool.** The console surface gains `list_categories`: each active
  category's slug, name, `is_security` and description, the description
  wrapped as untrusted text (BR-F15-10), since a person wrote it. Inactive
  rows are left out.
- **No fixed list.** The console tools' `corrected_category` and
  `to_category` were the six slugs as a `Literal`; they are now any slug,
  and core-api refuses one that is unknown or inactive, as for a person.
- **Employees.** The chat surface has no category tool, and employees still
  don't hold `categories:read`: nothing an employee's agent does needs the
  list. That closes the last part of open question 4.

## Open questions

The owner answered 1, 2 and 4 on 2026-11-26.

1. **Answered: a manager, with a reason.** A manager changes a category's
   description; the change is audited with the old and new text and bumps
   `version`. This relaxes decision 4: a manager's edit reaches Jev with no
   eval run. Part 2 records the categories and their versions in each
   routing decision, so a decision can be traced to the description it was
   made with and replayed. It comes with or after part 2, since before it
   Jev reads `category.v2.json`, not the rows.
2. **Answered: a manager, with a reason**, audited, turns `is_routable` on
   or off. Still open: how the per-category F1 floor (hard rule 9) covers a
   category a manager makes routable, since the eval in CI reads the golden
   set and never sees a switch in the database.
3. **Built as proposed, not yet confirmed.** Per-category workflows: move
   the ticket into its category's workflow at handoff, at the status with
   the same key? Does a reviewer's category correction move it again? The
   owner also asks whether a category can be marked to enter its workflow
   automatically or not. Before part 3 every ticket started in the default
   workflow and stayed there: workflow rules can't see the category, and
   the "Change workflow" action runs on a workflow's own events and refuses
   a ticket still in triage. Proposed, and built in part 3: the category's
   nullable `workflow` is that switch; a category without one leaves its
   tickets in the default workflow; a reviewer's correction is the category
   the ticket is handed off with, so it decides the workflow. Still open:
   whether a reopen or a reassign to another category should move the
   ticket again (part 3 leaves it where it is).
4. **Answered: read only.** The agent reads the category list
   (`GET /api/categories` at `AgentTier.READ`, part 4) and never changes it.
   A ticket's category is still Jev's choice in triage. The agent acts as
   the person, and employees don't hold `categories:read`: part 4 gives
   only the console (staff) surface a category tool, so employees keep
   no read access.

## Consequences

- A new category is added as a row plus an owning team: from part 2 Jev
  is offered it, and the router routes into it once it is routable. Part 1
  alone offered it in pickers, refused it where the request schema was
  still the enum, and never offered it to Jev.
- Deactivating one of the six before part 2 leaves it in Jev's question:
  tickets still land in it and, with no owning team, go to the fallback
  team, audited `no_team_for_category`. No route deactivates a category in
  part 1.
- Once a manager can edit a description (open question 1), what Jev is
  told about a category can change with no eval run. This is a deliberate
  relaxation of decision 4 and of eval-gating classifier input.
- `classification.min_confidence` (0.65) was chosen on six categories; a
  larger set spreads Jev's probability and needs it re-chosen.
- Per-category F1 (hard rule 9) must cover every routable category.
- From part 3 a category's workflow decides which statuses, rules and
  actions its tickets meet after handoff, so a misrouted ticket can start
  in the wrong workflow. A reviewer's correction moves it; after handoff a
  person moves it with "Change workflow".
