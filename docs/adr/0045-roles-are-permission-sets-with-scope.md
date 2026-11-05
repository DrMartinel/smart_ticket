# ADR-0045: Roles are permission sets, granted with a scope

**Status:** Proposed (2026-11-05). Needs the owner's acceptance and the Information Security Officer's sign-off.
**Date:** 2026-11-05
**Supersedes (when accepted):** ADR-0031 §1–§3 (fixed roles and capabilities as the unit of access), ADR-0042 §1 for *what* a role is (who sets it stays the console)
**Builds on:** ADR-0002, ADR-0006, ADR-0029, ADR-0041, ADR-0042, ADR-0043
**Spec:** [06-F14-org-access.md](../requirements/phase-2/06-F14-org-access.md)

## Context

Access is four fixed roles and three capabilities, checked by name in 107
route gates and 71 service checks. A new kind of job (auditor, report
reader, holiday cover) needs a code change. Rights are global, so a manager
manages every team. Requesters belong to no department, so reports, SLA
policies and department heads can't use one. On 2026-11-02 the owner chose
"permissions in code, roles as data" (option 1); it was deferred, and
ADR-0042 then moved role assignment into the console.

## Decision

1. **Permissions are a fixed enum in code, named by URN** (`urn:smart-ticket:perm:<area>:<action>[:<qualifier>]`); code checks permissions, never role names. A permission URN never changes or gets reused, and there are no wildcard grants.
2. **Roles are data:** a set of permissions and the scopes they may be granted at. System roles reproduce today's matrix and can't be edited.
3. **A role is named by an immutable URN,** `urn:smart-ticket:role:<system|custom>:<name>` (RFC 8141). Renaming changes only the display name; a retired URN is never reused; only code defines `system` URNs.
4. **A grant is (person, role, scope, start, end?)**, with scope = global, a department subtree, or a team. One person may hold many grants.
5. **Some permissions are locked to system roles:** KB authority, critical PII reveal and the PII access log, security queues, rollout flag on, access admin, break-glass.
6. **No escalation, no self-change, at least one access admin.** A change applies at once with a reason (ADR-0043) and ends the person's sessions. The audit row is the only record; security is not notified.
7. **Departments are core-api data,** in a tree; every person is in one. Keycloak still proves identity only.
8. **Migration preserves behaviour:** an equivalence test over every route and every current (role, capability) combination must pass before anything new is switched on.
9. **Access never reaches routing, the trust score, ai-engine or a prompt.**

## Consequences

- New jobs become data, but a badly built custom role can widen access quietly. Mitigations: locked permissions, no-escalation, access reviews and the explain view. There is no security notice, so a quiet widening is caught only by a review or by someone reading the audit log.
- One more evaluator (`Access`) on every request, cached per person's `access_version`.
- About 180 gate and check sites and 47 frontend files change. This is spread over four PRs, the first with no behaviour change.
- Role and permission URNs appear in session claims, audit rows and exports, so they must never be renamed. A wrong name stays as a retired role.
- An employee never holds an add-on role, and team-lead rights are a system role.
- `team_scope` in reports and every role-named queryset move to `Access`.
