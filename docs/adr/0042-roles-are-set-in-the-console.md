# ADR-0042: Roles and capabilities are set in the console

**Status:** Accepted (2026-11-04), the owner's decision
**Date:** 2026-11-04
**Supersedes:** ADR-0031 §4 for roles and capabilities, ADR-0032 §3, BR-F13-02, BR-F13-03 and BR-F13-05, and AC-F13-02…04 ([06-F13-identity.md](../requirements/phase-2/06-F13-identity.md))
**Builds on:** ADR-0031 (roles, capabilities and team scope), ADR-0032 (Keycloak sign-in), ADR-0041 (teams live only in core-api)

## Context

ADR-0032 read a company sign-in user's primary role and capabilities from
`smart-ticket` client roles at each sign-in and identity sync, and refused
console edits to them. Giving someone a role meant asking IT, and the
console showed no place to do it. ADR-0041 already moved teams into
core-api.

The owner wants Keycloak to prove only who a person is, and core-api to
hold everything about what they may do.

## Decision

1. **Roles and capabilities are core-api data** for every account. A
   manager sets them in Admin → Settings → People
   (`PUT /api/accounts/people/{username}/rights`, `AccountRights.assign`);
   a manager or workflow admin can list people. The change applies at once,
   with no second approval, and needs a reason; it is audited as
   `rights_changed`.
2. **A change ends the person's sign-ins** (`rights_changed`), so their
   next session carries the new rights.
3. **Refusals:** nobody changes their own rights (`own_rights`); a
   break-glass account stays a manager (`break_glass_fixed`); an employee
   holds no capability (`capability_needs_staff`) and no open assigned
   ticket (`has_open_tickets`). Becoming an employee leaves every team.
4. **Keycloak roles mean nothing to Smart Ticket.** Sign-in and identity
   sync read neither client roles nor groups; the realm needs no mapper. A
   first company sign-in creates an `employee`. Identity sync only
   deactivates leavers (`not_in_keycloak`, `disabled_in_keycloak`), and its
   service account needs only `view-users`.
5. **Migration `accounts.0007`** drops `User.rights_synced_at` and
   `UserCapability.source`. Rights set from Keycloak before it stay, as
   ordinary rights.

## Consequences

- Anyone who can complete a company sign-in gets the employee pages; before,
  a person with no client role was refused (`no_access`, now only for local
  and break-glass accounts at the company sign-in).
- A manager can make another person a manager alone. The audit row is the
  only record; nobody else confirms it.
- `ambiguous_role` and `identity_claims_ignored` are no longer raised; old
  alerts and audit rows keep their kinds.
