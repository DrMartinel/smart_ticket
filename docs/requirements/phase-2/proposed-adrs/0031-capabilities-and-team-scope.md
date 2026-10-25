# ADR-0031: Capabilities and team scope alongside the primary role

**Status:** Proposed (phase 2 pack, stage 2). Copied to [`docs/adr/0031-capabilities-and-team-scope.md`](../../../adr/0031-capabilities-and-team-scope.md); its status there is the one that counts
**Date:** 2026-10-17
**Builds on:** `apps/accounts` (`User.role`), ADR-0002
**Features:** F2, F6, F7, F9, F13 ([personas](../04-personas.md))

## Context

`User.role` holds one of `employee`, `technician`, `manager`, `security`.
Phase 2 needs a team lead, a workflow admin, a KB editor and an incident
manager. Adding them as roles would force "technician **or** KB editor" when
people are both, and would multiply every `require_role` list.

## Decision

1. **Primary role stays single** and keeps its meaning.
2. **Capabilities** are a fixed enum (`workflow_admin`, `kb_editor`,
   `incident_manager`) in `accounts_user_capabilities`. Code checks them with
   `require_access(roles=…, capabilities=…)`: allowed if the role **or** a
   capability matches.
3. **Team scope**: `team_memberships.role` is `member` or `lead`. Lead rights
   apply only inside that team; checked in the service, not the decorator.
4. **Source of truth is Keycloak** for `oidc` users (ADR-0032); core-api
   refuses local edits (`managed_by_idp`).
5. **No capability grants KB auto-reply authority.** That stays `manager`
   only (ADR-0002).

## Consequences

- `GET /api/accounts/me` returns capabilities and teams.
- A route test (PRE-1) checks every route declares roles or capabilities.
- Granting a capability is a Keycloak change, audited there and on sync.
