# ADR-0040: Workflow statuses carry their own kind

**Status:** Accepted (2026-11-04), the owner's decision
**Date:** 2026-11-04
**Supersedes:** ADR-0028 §1's global `SystemStatus` and the "system status base" of BR-F3-05 and the F3 requester label table ([06-F3-requester-chat.md](../requirements/phase-2/06-F3-requester-chat.md))
**Builds on:** ADR-0028 (configurable lifecycle), ADR-0030 (SLA clocks), ADR-0031 (assignment)

## Context

ADR-0028 mapped every workflow status onto one of a global list of system
statuses (Intake, Open, In progress, On hold, Resolved, Closed), managed on
their own admin page. Nothing read a system status's identity: the SLA
clocks, workload counts, reports, requester notices and `resolved_at` read
only its two flags, `is_backlog` and `is_completed`. The requester portal
read its name, through a fixed name-to-label table.

A system meant for several kinds of support work should not carry a fixed
list of stages that every workflow has to map onto.

## Decision

1. **A workflow status carries its kind.** `WorkflowStatus.kind` is one of
   `backlog` (not started), `active` (in progress) or `completed`
   (resolved). Each workflow sets it per status; the status name is free.
   `SystemStatus`, its admin page and its endpoints are gone.
2. **The kind is what code acts on.** Entering a `completed` status stops the
   SLA clocks and sets `resolved_at`; entering a `backlog` one cancels them;
   workload and reports leave out `completed` tickets. The kinds are code,
   like `pauses_sla`; which status has which kind is data.
3. **A pipeline status keeps whether it counts as resolved**, as before:
   only `auto_replied` is `completed`.
4. **Requesters see the kind, not the status**: Đang tiếp nhận / Received,
   Đang xử lý / In progress, Đã giải quyết / Resolved, and Chờ bạn phản hồi /
   Waiting for you on a status that pauses the SLA. Every status a person
   works in, including *Pending review*, *Blocked* and *Escalated*, reads as
   In progress.
5. **Migration `lifecycle.0006`** gives each status the kind its system
   status meant, renames the `{{ticket.baseStatus}}` placeholder in saved
   actions to `{{ticket.statusKind}}`, and drops the system statuses. It
   reverses onto three system statuses (Intake, Open, Resolved).

## Consequences

- Requesters no longer see *Waiting for support*, *On hold* or *Closed*:
  those read as In progress or Resolved.
- A grouping across workflows finer than the three kinds (say, every
  "waiting on vendor" status) has no home; it would need a new field.
- `StatusOut.stage` on a ticket is now `kind`; the `statuses/by-base`
  endpoint is gone.
- Migration `lifecycle.0002` holds a frozen copy of the seed it was
  written against.
