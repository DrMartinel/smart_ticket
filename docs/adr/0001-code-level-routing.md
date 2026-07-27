# ADR-0001: Routing decisions are made by code, not by the LLM

**Status:** Accepted
**Date:** 2026-07-27

## Context

The LLM (`ai-engine`) produces a proposal: which KB article answers the
ticket, which team it belongs to, or that it doesn't know. Someone will
eventually suggest "just let the model decide the branch too — it already
has all the context, and a routing prompt is simpler than a rule engine."

## Decision

`services/core-api/apps/tickets/services/router.py::route()` is the only
place in the system allowed to decide `Branch`. It is a pure function: no
I/O, no LLM call, thresholds passed as an explicit parameter. The LLM never
sees `Branch`, never sees thresholds, and has no field in its output schema
that maps to a branch.

## Consequences

- The router can be unit-tested exhaustively (every hard gate, every
  threshold boundary) without a model, a network call, or flakiness.
- A prompt change can never silently change routing behavior — the two are
  structurally decoupled.
- The cost is an extra hop: the LLM's `proposed_intent` and the router's
  `Branch` are different vocabularies that must be kept conceptually
  aligned by hand. This is intentional friction — see ADR-0003 for why we
  don't want that friction removed by trusting model self-assessment.

## Why this will be relitigated

"For flexibility" is a plausible-sounding argument for LLM-driven routing.
It is wrong here because flexibility in routing means flexibility in *when
a human gets bypassed*, and that is exactly the property this system needs
to hold constant while everything else (prompts, retrieval, models) changes
underneath it.
