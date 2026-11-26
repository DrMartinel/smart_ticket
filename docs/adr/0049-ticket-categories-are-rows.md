# ADR-0049: Ticket categories are rows in `ticket_categories`

**Status:** Accepted for part 1 (2026-11-26): decisions 1–4 are built. Part 2's switch to `is_security` (decision 5) and parts 2–4 are proposed and wait on the open questions below.
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
- **Part 3:** a category may name a workflow; a ticket moves into it at
  handoff.
- **Part 4:** an agent-readable category route, once the F15 tier table
  names it.

## Open questions

1. Who may change a category's description, and how: a second person's
   approval like KB drafts (ADR-0036), a manager with a reason, or a pull
   request only?
2. Who turns `is_routable` on, and on what evidence (an eval run with
   golden tickets in that category)? Should the eval report fail when a
   routable category has no golden tickets?
3. Per-category workflows: move the ticket into its category's workflow at
   handoff, at the status with the same key? Does a reviewer's category
   correction move it again?
4. What the agent uses the category list for, which decides its tier.

## Consequences

- A new category can be added as a row plus an owning team, but until
  part 2 the classifier and the router still know only the six in the
  enum and `category.v2.json`. A seventh row would be offered in pickers,
  refused by the routes whose request schema is still the enum (team
  categories, a reassignment's `to_category`, SLA policies, KB drafts),
  and never chosen by Jev.
- Deactivating one of the six before part 2 leaves it in Jev's question:
  tickets still land in it and, with no owning team, go to the fallback
  team, audited `no_team_for_category`. No route deactivates a category in
  part 1.
- `classification.min_confidence` (0.65) was chosen on six categories; a
  larger set spreads Jev's probability and needs it re-chosen.
- Per-category F1 (hard rule 9) must cover every routable category.
