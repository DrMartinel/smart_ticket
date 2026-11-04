# ADR-0043: One person applies a change; no second approver

**Status:** Accepted (2026-11-04), the owner's decision. **Relaxes a guardrail.**
**Date:** 2026-11-04
**Supersedes:** ADR-0035 §3 and §4 (two managers to turn a flag on, two approvers of a threshold change), the second-manager rule for gate changes (BR-F9-04), ADR-0038 §1 and §5 (a manager approves catalog changes, a second manager for high-risk runs), the `require_approval` workflow action of ADR-0028, BR-F1-12 / AC-F1-08, BR-F9-02 / AC-F9-02, BR-F9-06, BR-F12-03 / AC-F12-03, BR-F12-08 / AC-F12-06
**Builds on:** ADR-0006 (unchanged), ADR-0035, ADR-0038, ADR-0042

## Context

Seven operations waited for a second person: activating an SLA policy,
a runbook catalog change, a high-risk runbook run, a threshold change
request (two approvals, one a manager's), turning a rollout flag on, a
rollout gate change, and a workflow move with a `require_approval` action.
The owner finds the second step redundant for a team this size: the person
allowed to make the change is trusted to apply it.

## Decision

1. **SLA policies:** a workflow admin or manager drafts and activates,
   their own draft included (`POST /api/sla/policies/{id}/activate`, with a
   reason). "Save and activate" does both.
2. **Runbook catalog:** a workflow admin's create or change is live at
   once (`approved_by` = the author). A run queued before a change still
   fails rather than run the old definition. `activate` turns on a
   runbook that was never live (the seed).
3. **High-risk runbooks** run on the reviewer's approval alone. ADR-0006 is
   unchanged: every runbook still goes to a person, and `execute` and the
   worker still refuse without an approving review decision.
4. **Thresholds:** only a manager writes a change request; submitting it
   approves it. It still ships by PR under its id, and a loaded file that
   matches no approved request still keeps every branch in shadow.
5. **Rollout flags:** one manager turns a branch on at once
   (`POST /api/rollout/{branch}/on`), with a reason and an override reason
   for any gate not met. Off is unchanged.
6. **Gates:** one manager's change applies at once and is audited.
7. **Workflows:** the `require_approval` action is gone. Migration
   `lifecycle.0007` deletes saved ones, cancels moves they held, and drops
   `lifecycle_approval_requests`.
8. Every change still needs a reason where it did and writes its audit row.
   Leftover pending rows are closed by `itsm_mock.0004`, `rollout.0003` and
   `notifications.0005` drops the four approval events.

## Consequences

- **One manager can put automation live alone.** Trust-score coefficients
  and `t_auto` / `t_route` are still hand-set placeholders; nothing in code
  now stops a single manager from turning `auto_reply` on before
  calibration. The gate override reason and the audit row are the only
  record.
- A technician can no longer propose a threshold change.
- BR-F9-06 applied hard rule 9's outside-reviewer principle to live
  numbers; it no longer does. Hard rule 9 itself (eval floors and
  baselines) is unchanged.
- KB drafts still need a second person (ADR-0036), and KB auto-reply
  authority stays a manager's (ADR-0002): neither was in scope.
- `thresholds.yaml` still has `lifecycle.approval_wait_hours` and
  `rollout.flag_request_expiry_hours`, now unread; removing them needs a
  threshold change request of its own.
