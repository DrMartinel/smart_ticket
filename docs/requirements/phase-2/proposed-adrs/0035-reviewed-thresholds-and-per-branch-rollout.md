# ADR-0035: Reviewed thresholds and per-branch rollout switches

**Status:** Proposed (phase 2 pack, stage 3). Copied to [`docs/adr/0035-reviewed-thresholds-and-per-branch-rollout.md`](../../../adr/0035-reviewed-thresholds-and-per-branch-rollout.md); its status there is the one that counts
**Date:** 2026-10-17
**Builds on:** ADR-0001, ADR-0006; CLAUDE.md hard rules 1, 2, 9; spec §8.2, §14
**Feature:** F9 ([spec](../06-F9-rollout-control.md))

## Context

`SHADOW_MODE` is one env var for every automated branch. The rollout plan
turns branches on one at a time (P3 auto-route, P4 auto-reply), each after a
measured gate. `thresholds.yaml` is the only home of tunables and is
snapshotted into every decision, but nothing proves a change to it was
reviewed before it acted on real tickets.

## Decision

1. **Live is decided per decision, outside the router**, as
   `env SHADOW_MODE is false AND branch flag is on AND loaded thresholds are
   approved`. `router.py` and `route()` don't change; the same decision runs
   in both modes (spec §8.2).
2. **Flags exist for `auto_route`, `auto_reply`, `requester_questions`.**
   None exists for runbooks (ADR-0006).
3. **On takes two managers, neither the requester; off takes one manager or
   security, at once.** The risky direction is the slow one.
4. **`thresholds.yaml` stays the source.** A change is a change request
   holding the full file, approved by two people who are not the author,
   then shipped by PR with `version` set to the request id.
5. **At boot core-api hashes the file.** If no approved request matches, every
   branch is shadow and security is alerted. Local dev and CI may disable the
   check; production can't.
6. **Each decision records the flags it ran under** (`rollout_snapshot`).

## Consequences

- Turning automation off needs no deploy; turning it on needs a deploy only
  when thresholds change.
- A hand-edited production `thresholds.yaml` degrades to shadow instead of
  acting.
- One extra hash at boot and a small lookup per decision.
