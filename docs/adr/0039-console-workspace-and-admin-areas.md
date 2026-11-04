# ADR-0039: The admin console has a Workspace and an Admin area

**Status:** Accepted (2026-11-02), the owner's decision
**Date:** 2026-11-02
**Supersedes:** the console navigation in the phase 2 pack: [mockups.md](../requirements/phase-2/mockups.md) line 107 and assumption A-17 ([09-risks-open-questions.md](../requirements/phase-2/09-risks-open-questions.md) line 64)
**Builds on:** ADR-0002 (authority on KB rows), ADR-0035 (rollout flags and reviewed thresholds), ADR-0036 (KB drafts)
**Amended by:** ADR-0040 (the Stages page is gone; each workflow status carries its kind)

## Context

`services/admin-console` grew one sidebar for two jobs: staff handling
tickets every day, and managers and admins running the system (figures,
authority, rollout, thresholds, settings). The pack's mockups put both under
one top nav, with rollout and thresholds inside Settings. In use, the two
jobs crowded each other, and "admin console" read as the place staff work
tickets, which it is only in part.

## Decision

1. **One app, two areas.** The Workspace keeps its paths (`/tickets`,
   `/board`, `/sla`, `/incidents`, `/teams`, `/kb`, `/security/alerts`,
   `/security/access-log`, `/me/*`). Admin pages live under `/admin/*`. The
   area is read from the path; the service and its name stay.
2. **Admin holds** three groups:
   - Insights: dashboard, reports, the managers' security summary.
   - Governance: the authority queue, all help pages (the manager's
     allow/revoke), the authority log, rollout, thresholds.
   - Settings: workflows, stages, SLA policies, calendars, holidays, teams,
     notifications, deliveries, runbooks, webhooks.
3. **The Workspace holds** tickets, teams, KB content (pages read-only,
   graph, drafts, gaps), and the security team's alerts and PII access log.
   Security staff reach Admin for their report, the authority log and the
   rollout off switch.
4. **A switcher** at the top of the sidebar moves between the areas. It shows
   only to a user with at least one Admin page.
5. **Role gates do not change.** Each page and each API route checks the
   same roles as before; the area only decides where a link sits.
6. **Old paths redirect** (`next.config.mjs`), so saved links and
   notifications sent before the split still open the right page. New
   notification links point at `/admin/*`.

## Consequences

- A page's automatic-answer authority changes only in Admin (the queue or
  All pages); the Workspace list shows it but has no toggle.
- Adding a console page means choosing its area: daily work goes in the
  Workspace, anything that changes how the system behaves for everyone goes
  in Admin.
- The getting-started guide introduces both areas and the switcher.
