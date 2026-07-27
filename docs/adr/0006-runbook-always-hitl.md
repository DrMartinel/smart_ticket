# ADR-0006: Runbook execution always goes through HITL — no threshold ever bypasses it

**Status:** Accepted
**Date:** 2026-07-27

## Context

This is the guardrail most likely to erode, and it is being written down
now, before there is any pressure to erode it.

A `RunbookProposal` is a draft action against a *real system* (the ITSM
mock today; a real ITSM/IAM/infra API tomorrow) — resetting a password,
granting access, restarting a service. Unlike an auto-reply, which is
wrong information a user reads, a runbook executed on bad grounds is a
state change in a live system, potentially one that is hard or impossible
to cleanly undo.

Once `automation_rate` (spec §11.1) becomes a KPI someone is measured on,
there will be direct pressure to raise `t_auto` for runbooks the same way
it's raised for auto-reply, or to introduce a "high-trust runbook"
fast path. That pressure is predictable and legitimate-sounding
("we've had 2,000 clean approvals of this exact runbook, why review
#2,001?") which is exactly why it needs to be pre-empted in writing.

## Decision

In `router.py`:

```python
if isinstance(proposal.root, RunbookProposal):
    return _hitl(
        ReasonCode.ALL_CHECKS_PASSED,
        queue="runbook_approval",
        draft_payload=proposal.root.draft_payload,
    )
```

There is no `trust` comparison in this branch. No threshold value, no
matter how high, routes a `RunbookProposal` anywhere except
`runbook_approval`. `apps/itsm_mock`'s execute endpoint additionally
refuses to run a runbook unless a `review_decisions` row with
`action_taken` approving it actually exists — so even a bug that skipped
the router check would still be caught at execution time.

## Consequences

- Runbook-eligible tickets have a hard ceiling on automation rate that
  auto-reply and auto-route don't share, by design.
- If/when a specific, extremely low-risk runbook genuinely deserves a
  higher-automation path, that requires a **new ADR that explicitly
  supersedes this one** — not a threshold tweak, not a config flag, not a
  "temporary" exception. The bar for changing this decision is a written
  argument, on the record, not a config diff in a routine PR.
