# ADR-0030: SLA clocks count business time, driven by lifecycle status events

**Status:** Accepted (2026-10-26), the owner's decision
**Date:** 2026-10-17
**Builds on:** ADR-0028 (configurable lifecycle), ADR-0001
**Feature:** F1 ([spec](../requirements/phase-2/06-F1-sla.md))

## Context

The brief asks for SLA "built on lifecycle actions". Clocks must start when a
ticket is handed to support, which is a move into `pending_review`,
`auto_routed` or `escalated`. Those are pipeline statuses: by ADR-0028 §2
they carry no actions and `system_move` runs none. The only existing SLA
action, `set_sla`, adds wall-clock hours. A clock that pauses for the
requester also needs a status people can enter; `awaiting_requester` is
triage-only.

## Decision

1. **Clocks follow status events, not actions.** The engine calls
   `SlaClocks.on_status_entered(ticket, before, after, transfer)` right after
   `ticket.enter_status()` in both `record_system_transfer` and
   `commit_locked`: the two places every status change passes.
2. **The hook can't fail a move.** It runs in a savepoint. An error rolls back
   the savepoint only, is audited (`sla_update_failed`), and the sweep
   rebuilds the clocks from `lifecycle_transfers`. `system_move` still never
   fails for a workflow reason.
3. **Start, pause, stop are defined by status data:** start = first status
   whose base is neither backlog nor completed; pause = a status with
   `pauses_sla`; stop = a completed base. No free condition expressions
   (ADR-0028 §5).
4. **Business time** is computed in the calendar's IANA zone, from weekday
   working intervals and dated whole-day holidays, stored in UTC.
5. **Clocks keep a snapshot** of targets and calendar id, like
   `routing_decisions.thresholds_used`.
6. **`set_sla` stays an action** and becomes a business-time override of the
   resolution target, audited.
7. **`waiting_on_requester`** is added as an ordinary, person-enterable status
   with `pauses_sla = true`.

## Consequences

- One indexed write per status change for tickets after handoff.
- SLA configuration (policies, calendars, holidays) is data; percentages and
  sweep interval are in `thresholds.yaml` / `.env.example` (BR-X-01).
- A test pins that `system_move` succeeds when the hook raises.
