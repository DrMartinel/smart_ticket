# ADR-0041: Teams live only in core-api

**Status:** Accepted (2026-11-04), the owner's decision
**Date:** 2026-11-04
**Supersedes:** ADR-0031 §4 for team memberships, the "team groups" of ADR-0032 §3, FR-F2-015 ([06-F2-teams-assignment.md](../requirements/phase-2/06-F2-teams-assignment.md)) and the teams half of BR-F13-03 ([06-F13-identity.md](../requirements/phase-2/06-F13-identity.md))
**Builds on:** ADR-0031 (roles, capabilities and team scope), ADR-0032 (Keycloak sign-in)

## Context

ADR-0031 and ADR-0032 took a company sign-in user's teams from Keycloak
groups (`/it/<team>`, `/it/<team>/lead`) at each sign-in and identity sync,
and refused console edits to them. A team created in the console had no
members who sign in through Keycloak until IT created the matching group,
and the team's `keycloak_group` field was stored but never read.

The owner wants Keycloak to hold who a person is and what role they have,
and core-api to hold the organisation: teams and who is in them.

## Decision

1. **Team memberships are core-api data** for every account, local or
   company sign-in. A manager or workflow admin adds, removes and changes
   members and leads in Admin → Settings → Teams.
2. **Keycloak groups mean nothing to Smart Ticket.** Sign-in and identity
   sync read only the client roles (primary role and capabilities); the
   `groups` claim is not read, and the realm needs no group mapper.
3. **Only active support staff** (technician, manager, security) can be
   team members (`not_support_staff`).
4. **Migration `teams.0005`** drops `Team.keycloak_group` and
   `TeamMembership.source`. Memberships made from groups before it stay, as
   ordinary memberships.

## Consequences

- Moving someone between teams no longer needs IT; a leaver still loses
  access through Keycloak (deactivation is unchanged).
- Leaving a Keycloak group no longer removes anyone from a team.
- Runbooks still grant only groups under `ITSM_GRANTABLE_GROUP_PREFIXES`.
- Roles and capabilities still come from Keycloak (ADR-0031 §4 stands for
  them).
