# ADR-0046: The agent acts as the signed-in user, through tiered routes

**Status:** Accepted (2026-11-07), the owner's decision, with every recommendation in
[06-F15 §k](../requirements/phase-2/06-F15-agent.md#k-open-questions)
(amendment to decision 12 and a new decision 17: Accepted, 2026-11-26)
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
    *Amended 2026-11-26:* an invalid model reply is asked again once, in the
    same `choose_action` step, with a sentence written by code saying what
    was wrong; only a second invalid reply stops the turn. The re-ask comes
    before any tool call and counts against the turn's step and token caps.
    A hosted model with JSON mode but no schema-constrained output
    (DeepSeek, the template's agent model since that day) drops the
    `call_tool` envelope on some replies, and answers others with only
    whitespace (a blank reply is invalid, not a model failure: the model
    answered, so it is asked again too); stopping there sent requests a
    second ask gets right to a person. Tool calls and writes are still never
    retried.
    *Amended 2026-11-26 (2):* an employee's hand-off opens its ticket only
    when the employee presses "Open a ticket" on the turn
    (`POST /api/agent/turns/{id}/ticket`, once however often it is pressed).
    Until then the turn only offers one (`ticket_offered`) and no ticket row
    exists. A turn whose masking failed or that holds critical PII still
    becomes a ticket with the hand-off: a person has to see it whether or not
    it is asked for, and the security alert names it. A ticket opened either
    way is never held for the employee (`waits_for_requester`), since the
    employee has already been asked. Opening a ticket at every hand-off and
    holding it as `awaiting_requester` filled each employee's ticket list
    with tickets nobody asked for.
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

## Amendment (2026-11-26): the agent asks with choices and hands off on purpose — Accepted

**Spec:** [06-F15 amendment](../requirements/phase-2/06-F15-agent.md#amendment-2026-11-26-the-agent-finds-out-asks-and-says-why--accepted)

### Context

The agent could do two things: call a tool or reply. While F17 §o was being
written, each edge case it met got its own rule: a tool just for asking which
resource a customer meant, and a fixed list of requests the chat can't do, each
with its own text. The owner asked for an agent that notices what it is
missing and finds it out, instead of a rule per case. Two things it needs touch
this ADR:

1. **Choices.** A typed answer to "which server?" ("the second one", "db1") is
   something code can't use. Buttons would be exact, but a button the model
   invents could name something the person can't see.
2. **A hand-off on purpose.** Decision 12 says the person is told why a turn
   stopped "in words code chose". That fits failures. It doesn't fit "you asked
   for something only staff can do", where the reason depends on the request.

### Decision

12. *Amended (2026-11-26):* on the chat surface the model may end a
    turn on purpose with `hand_off` when the person asks for a change none of
    their tools makes. The reason is the model's own text. core-api then adds
    what it knows as fact, in words it chose: that what the turn checked goes
    with the ticket, the "Open a ticket" button, and the ticket's id once
    pressed. The stop gets its own `ReasonCode`, `agent_needs_staff`, and the
    router still sends the ticket to a person (decision 13). The model's
    summary of the request is stored on the ticket for staff only; it is never
    sent to triage and nothing reads it to decide. Every other stop keeps its
    fixed text, and the console surface has no `hand_off`.
17. **The model offers only what its tools returned.** Every item a person
    could pick in a tool result gets a ref, stable within the turn. A reply
    may offer up to `agent.max_choices` refs as buttons; ai-engine resolves
    them from the turn's own results, and a ref the turn never issued makes
    the reply invalid. core-api builds the card and always adds "Something
    else". A press sends the button's label as the person's next message, and
    nothing the model sends records a choice. A feature that needs the pressed
    item itself checks it again through its own route (F17's resource picks).

### How the earlier decisions still hold

- **Decision 4.** A ref exists only for what the person's own token returned,
  so a card can't show more than they can see.
- **Decision 11.** What was done is still reported from tool outcomes. A
  hand-off's text explains a refusal; it reports nothing as done, and the
  ticket and button beside it are code's.
- **Decision 12.** The re-ask of an invalid reply covers an unknown ref and a
  malformed `hand_off`, as it covers any invalid reply.
- **Decision 13.** The agent still never chooses a branch.

### Consequences

- The agent's handling of edge cases is now model behaviour, measured by the
  live agent eval's cases (`evals/golden/agent_cases.jsonl`) rather than
  written as rules. It counts only once that eval runs (TODO 23).
- A hand-off's reason can be wrong or badly put. The ticket still reaches a
  person, with the turn's receipts.
- The wire gains a third action shape, choices and a summary, in both
  services (ADR-0010).

### Alternatives considered

- **A fixed list of requests, each with a fixed text** (the first draft).
  Safe wording, but every new request needs a list entry in both services, a
  text in two languages and a ticket subject, and anything not listed falls to
  "other".
- **A tool per kind of question** ("ask which resource"). Each new kind of
  question needs a route and a tool.
- **Choices the model writes freely.** It could offer a server the person
  can't see, or one that doesn't exist.
