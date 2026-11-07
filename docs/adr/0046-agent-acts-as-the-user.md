# ADR-0046: The agent acts as the signed-in user, through tiered routes

**Status:** Accepted (2026-11-07), the owner's decision, with every recommendation in
[06-F15 §k](../requirements/phase-2/06-F15-agent.md#k-open-questions)
**Date:** 2026-11-07
**Builds on:** ADR-0001 (code routes), ADR-0003 (no self-confidence), ADR-0004
(ai-engine is read-only), ADR-0006 and ADR-0038 (runbooks always go through a
person), ADR-0007 (LangChain owns transport only), ADR-0012 (ai-engine is the
only model client), ADR-0029 and ADR-0032 (core-api keeps the session),
ADR-0034 (conversation context), ADR-0045 (permission URNs with scope)
**Touches:** `apps/accounts/permissions.py` (`SessionAuth`, `require`),
`AuditLog.objects.record`, `router.py` (one new hard gate), `graph/build/`
(bounded cycles), CLAUDE.md hard rules 1, 3, 4, 7
**Supersedes:** nothing
**Spec:** [06-F15-agent.md](../requirements/phase-2/06-F15-agent.md)

## Context

The chat answers one question per message: each message becomes a ticket,
the triage graph proposes, the router decides. People want more from it.
An employee wants to say "open a ticket for me" or "what happened to my VPN
ticket?" and have it done. A technician wants to say "summarise my queue" or
"take the oldest access ticket" without clicking through the console.

Doing that means a model chooses which endpoint to call next. That is new.
Until now the model's output was one proposal, read by code. An agent's
output is an action. If the action runs with ai-engine's own authority,
ADR-0004's boundary is gone. If it runs with more authority than the person
asking, rights quietly grow. If it can click "approve" on a review item,
ADR-0006 holds only on paper.

## Decision

1. **The agent is a separate graph in ai-engine.** It is built with
   `GraphBuilder` and typed outcome enums like the triage graph, and it may
   loop. Every loop passes through a node whose step limit routes out of the
   loop, and the builder checks this at startup. The triage graph does not
   change: it stays acyclic, its nodes and edges stay pinned, and its evals
   still gate it.
2. **Every tool is one HTTP call to an existing core-api route.** ai-engine
   gets no new database grant and writes nothing itself. A tool that changes
   something changes it through the same route, gate and service a person's
   click would use.
3. **The agent acts as the signed-in user, never as itself.** For each agent
   turn core-api mints a short-lived access token for that user. It carries
   `act=agent`, the user's live session family (`sid`), the agent
   conversation and the turn. `SessionAuth` accepts it only while that sign-in
   is live and that turn is running. It is never a refresh token and never
   reaches the browser.
4. **An agent token never holds more rights than its user.** The route's
   permission gate runs first and refuses exactly as it would refuse the user.
   `act=agent` can only take rights away.
5. **Every route declares an agent tier, and the default is refusal.** The
   tiers are `read` (called freely), `self` (called freely: the caller's own
   scope, easy to undo, touches nobody else's work), `confirm` (stored as a
   pending action; it runs only when the user sends the same call from the UI),
   `human_only` (refused with 403; a draft is stored for a person to apply),
   and `none` (refused, nothing stored). A route that declares no tier
   refuses `act=agent`, and a test fails the build if any route declares none.
6. **`human_only` covers every decision that is a staff judgement or reaches
   personal data:** review `decide` and `comment-decision`, runbook execute,
   `reassign`, `priority`, `sla/rebuild`, `quarantine/reveal` and every other
   PII reveal route.
7. **A draft is not a decision.** A person applies a `human_only` draft with
   their own session, through the route the draft names, and may change it
   first. The decision that results is that person's, recorded with
   `decided_via = human`. A runbook's approving decision must have
   `decided_via = human`, and `runbooks.run` checks this a second time.
8. **A confirmed action runs unchanged.** The UI resends the stored call
   with the user's own session and the action's id. core-api runs it only if
   the method, path and body hash match what the agent proposed and the
   action is still pending and unexpired. Its audit row says it was the
   agent's proposal, confirmed by the user.
9. **The model sees masked text only.** core-api masks the user's message to
   the agent inline, like a ticket, before storing it or sending it anywhere.
   A message whose masking fails never reaches the model. ai-engine screens
   the masked message for injection before the model sees it. Tool results
   are the masked fields core-api already returns, cut down to a fixed list
   per tool. Text from a ticket or comment marked `mask_failed` is withheld.
10. **Text other people wrote is untrusted data.** The prompt marks every
    such field as untrusted, and it grants nothing. A tool result that trips
    the injection screen makes the rest of the turn read-only.
11. **What was done is reported from tool outcomes, never from the model's
    words.** Each turn's reply carries receipts built by code from the HTTP
    results (done, waiting for your confirmation, draft waiting for a person,
    refused). The model's prose is shown beside them, never instead of them.
12. **The agent degrades toward a person.** On a step limit, a tool-call
    limit, a tool error, a write whose outcome is unknown, a model failure,
    an invalid model reply, a masking failure, an injection hit on the
    message or an unreachable ai-engine, the turn stops. The user is told
    plainly in words code chose, and the stop gets a specific `ReasonCode`.
    For an employee, the turn's masked message becomes a chat ticket carrying
    that reason, and the router sends it to a person. No write is ever
    retried.
13. **The router decides the hand-off branch.** A ticket that carries an
    agent hand-off reason meets a new hard gate in `Router.route()` and goes
    to HITL with that reason. The agent never chooses a branch.
14. **Every change made through an agent is audited as the user, via the
    agent.** Each `audit_log` row written while an agent token is in use
    gets `via = agent`, the agent conversation, the turn and the tool, in
    the same transaction as the change (BR-X-03). A refused agent call gets
    its own row.
15. **All limits are tunables.** Steps per turn, tool calls per turn, the
    token lifetime, the confirm and draft lifetimes and the agent's memory
    live in `thresholds.yaml` `agent:`. URLs, timeouts and the model
    provider live in `.env.example`. ai-engine receives the limits in each
    request; it reads no thresholds file.
16. **Access still never reaches ai-engine or a prompt (ADR-0045 §9).** The
    agent is given the fixed tool set of the surface it was opened on (the
    chat, or the console), never the user's permissions. A tool the user
    lacks returns the same 403 the user would get.

## How the earlier decisions still hold

- **ADR-0001 (code routes).** The agent picks which route to call; it never
  picks a `Branch`. A question still reaches triage only through
  `POST /api/chat/ask`: submit, triage, then `Router.route()`. A hand-off
  ticket's branch comes from the router's new hard gate, not from the agent
  (decision 13). No agent output is an input to the router.
- **ADR-0004 (ai-engine is read-only).** ai-engine's database role is
  unchanged, and no grant is added. Every change the agent causes is written
  by core-api, in a route's own service, after that route's permission check,
  as the user. ai-engine holds a user's token for at most one turn and can
  use it only on `read` and `self` routes. On a `confirm` route the user's
  click runs the call, and on a `human_only` route a person's decision does.
- **ADR-0006 and ADR-0038 (runbooks go through a person).** Review `decide`
  and runbook `execute` are `human_only`, so an agent token is refused before
  either handler runs. A decision made by applying an agent's draft is a
  person's decision, made with their own session. Execution checks twice
  that the approving decision was made by a person (decision 7). No
  threshold, flag or tier turns this off.

This ADR supersedes none of them.

## Consequences

- One more trust edge: ai-engine now calls core-api with a user's token. A
  compromised ai-engine could act as a user who has a turn running, for the
  token's lifetime, on `read` and `self` routes only. It still cannot decide,
  reveal, reassign or run anything.
- Every gated route gains a tier (229 of 237 today; the other 8 are sign-in
  and callback routes that take no bearer token). Most are `none`. A new route without
  a tier fails the route-walk test, so the choice is always visible in review.
- `AuditLog.objects.record` reads the request's agent context. Every row
  written while an agent token is in use is stamped, including rows a service
  writes deep in a call. A row written outside the request, such as a Celery
  task the call enqueued, is not stamped. That task's own trigger row is.
- The router gains a hard gate and its 100% branch-coverage gate covers it.
- An agent turn costs several model calls. The limits bound this, and the
  turn records tokens and cost like an AI run.
- A confirmed action needs the user's click, and a draft needs a person's
  decision. This is slower than "just do it", by design.
- What the model writes ("I approved it") can still be wrong. Receipts make
  the truth visible next to it. The live agent eval measures how often the
  prose and the receipts disagree.

## Decided with this ADR (owner, 2026-11-07)

The owner took every recommendation in 06-F15 §k:

- **Turns run in Celery** on their own `agent` queue, and the browser polls
  (OQ-F15-01).
- **Pending confirmations and drafts live in one `agent_actions` table**
  (OQ-F15-02). Confirm cards appear in the turn. A draft appears as a banner
  on its review item or ticket page, where a person applies it (OQ-F15-03).
- **An employee's hand-off ticket follows `waits_for_requester`** (OQ-F15-04).
- **The surface decides the tool set** (OQ-F15-05). Two F9 flags,
  `agent_chat` and `agent_console`, start off (OQ-F15-06). The template ships
  `vllm` (OQ-F15-07). The live agent eval is reported only until a baseline
  is reviewed (OQ-F15-08).
- **Refusals keep the BR-X-08 shape** (OQ-F15-09). Placeholder labels stay
  in tool results (OQ-F15-10). `none` is the explicit fifth tier (OQ-F15-11).
