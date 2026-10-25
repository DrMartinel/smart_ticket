# ADR-0038: Real runbook executors stay behind ADR-0006, with target rules

**Status:** Proposed (phase 2 pack, stage 4). Moved to [`docs/adr/0038-runbook-executors-behind-adr-0006.md`](../../../adr/0038-runbook-executors-behind-adr-0006.md); its status there is the one that counts
**Date:** 2026-10-17
**Builds on:** ADR-0006 (runbooks always go through a person), ADR-0028 (n8n action), ADR-0032 (Keycloak)
**Feature:** F12 ([spec](../06-F12-itsm-iam-integration.md))

## Context

Runbooks are simulated. Making them real raises two risks the mock hid: the
LLM proposes the target (a requester can ask to reset someone else's
password), and a real call can time out after it took effect.

## Decision

1. **The runbook catalog becomes data** (`itsm_runbooks`), changed by
   `workflow_admin` and approved by a manager.
2. **Executors:** `keycloak` (send a password-reset email, unlock, add to an
   allow-listed group — never handle a password), `n8n` (the existing signed,
   allow-listed call with a one-time callback), `mock` (tests).
3. **ADR-0006 is unchanged and checked twice:** the router always sends
   runbooks to HITL; `execute` refuses without a staff approving decision.
4. **Target rules don't rely on the reviewer:** a self-service runbook may
   target only the ticket's reporter.
5. **High-risk runbooks need a second manager.**
6. **A timeout after sending is `unknown`**, resolved by a person, never
   retried automatically.

## Consequences

- No runbook can be turned automatic by configuration; there is no flag for it
  (F9).
- Identity actions inherit Keycloak's own audit trail as well as ours.
