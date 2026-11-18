# ADR-0047: core-api checks an agent call's arguments, and one turn may propose several changes

**Status:** Proposed (2026-11-18), awaiting the owner's decision
**Date:** 2026-11-18
**Builds on:** ADR-0046 (the agent acts as the user, through tiered routes),
ADR-0006 and ADR-0038 (runbooks go through a person), ADR-0036 (KB drafts),
ADR-0045 §9 (no access in ai-engine)
**Touches:** `apps/accounts/permissions.py` (`require`), `apps/agent/utils/actions.py`
(action targets, limits), ai-engine `graph/agent.py` (the confirm edge),
`agent/tools/projection.py` (person handles), `thresholds.yaml` `agent:`
**Supersedes:** nothing. Every decision of ADR-0046 stands.
**Spec:** [06-F16-agent-capabilities.md](../requirements/phase-2/06-F16-agent-capabilities.md)

## Context

ADR-0046 gives every route one agent tier. That works for the 27 routes F15
opened. It falls short for the next routes worth opening:

- **One route, two judgements.** `POST /api/lifecycle/tickets/{id}/move`
  moves a ticket to *Waiting on customer* or to *Resolved*. The first is
  routine; the second closes the requester's issue. A per-route tier must
  either treat both as routine (`confirm`) or block the routine one
  (`human_only`). The same route takes `force`, which skips the workflow's
  rules.
- **One change per turn.** A confirm's 202 ends the turn (F15 build note
  14), so "take these three" is three turns.
- **No names, so no "who".** BR-F15-09 replaces every person with `you`,
  `someone else` or `none`. That is right for the model, but it makes
  workload and breach lists useless and `draft_reassign`'s `to_user`
  unusable.
- **Targets read from parameter names.** An action's target is guessed from
  the path parameter's name (`public_id` means ticket). Incident routes also
  use `public_id`, so an incident draft would be filed as a ticket's.

The tempting fix for the first case is to restrict the tool in ai-engine, for
example by leaving `force` out of the input model or not offering terminal
statuses. That enforces nothing: ai-engine holds no authority (ADR-0004,
ADR-0046 §2), and a compromised or confused ai-engine can send any body it
likes with the user's token.

## Decision

1. **A route may declare an argument guard, run by core-api.** It runs only
   for `act=agent`, after the permission gate and before the tier. It is a
   pure function of the route, the validated arguments and the target's
   state read before it. It returns *keep*, *raise the tier* or *refuse*
   (403 `agent_argument_refused`, nothing stored).
2. **A guard can only take rights away.** It may raise a tier (`self` →
   `confirm` → `human_only`) or refuse. It may never lower one, and it never
   runs for a person's own session. A test fails if a guard returns a tier
   below the route's declared one.
3. **The first guards:**
   - `move`: refuses `force`; raises a move to a `completed`-kind status to
     `human_only`.
   - `fields`: raises a write to a field that a `completed` transition
     requires to `human_only`.
   - `kb/drafts`: refuses anything but a `create` draft with no
     `proposed_risk_tier` and no gap cluster.
4. **Every `confirm` and `human_only` route declares its target kind.** The
   action store reads the target from the route, never from a parameter's
   name, and the route walk fails without one.
5. **One turn may propose up to `agent.max_actions_per_turn` changes.**
   Each is its own pending action with its own hash, numbered in proposal
   order. After a 202 the agent graph goes back to the model instead of
   ending. The user sees one card and applies each action with its own
   request, in order. One failing doesn't undo or block the others, and
   there is no route that applies a group as a whole. ADR-0046 §8 stands:
   each confirmed call runs unchanged.
6. **At most one action per target per turn may carry `expected_version`.**
   A second one is refused (409 `agent_action_conflicts`), because the
   first action's apply would make it fail.
7. **A turn that hits a limit with actions pending ends with its card, not
   a hand-off.** Its `stop_reason` still records the limit. Handing off
   would drop changes the user can still review.
8. **People reach the model as turn-stable handles (`person_N`).** ai-engine
   holds the handle map for the turn only, never in a prompt, step or log. A
   tool argument that names a person takes a handle, and ai-engine maps it
   back before the call. An unknown handle makes no call. This is a display
   rule, not a permission: core-api still checks every call against the
   token.
9. **An agent turn starts only from a person's message.** Nothing else, no
   schedule, event, webhook or task, starts one. This writes down what
   ADR-0046 §3 implies. A scheduled agent would need a token not minted from
   a live sign-in.
10. **The employee's assistant never gets a KB tool other than the
    helpdesk.** An employee's question is answered only through triage, the
    router and a page's authority. A KB search on the chat surface would let
    the model write an auto-reply that skips all three.

## How the earlier decisions still hold

- **ADR-0046 §4–§5 (rights never grow, default deny).** A guard comes after
  the permission gate and can only make a call harder, so an agent still
  can't do anything its user couldn't. The tiers are still declared per route,
  and a guard refines a tier, never replaces it.
- **ADR-0046 §8 (a confirmed action runs unchanged).** A group is several
  single confirmed calls. Nothing is approved in bulk.
- **ADR-0006, ADR-0038.** No guard touches review `decide`, runbook
  `execute` or `resolve`; they stay `human_only` with no guard.
- **ADR-0036.** An agent-made KB draft is the user's own draft. Review
  stays `none` for agents, and a second person still approves.
- **ADR-0045 §9.** Handles carry no access. ai-engine still receives no
  permission, role or grant.

## Consequences

- `require` grows two optional parameters (guard, target). Guards hold
  logic about arguments, so each needs its own tests, and each must stay
  pure, like `Router`.
- The agent graph's topology changes (the confirm edge), so its pinned
  topology test changes in the same PR.
- A turn costs more model calls when it proposes several changes. The
  existing step, tool and token limits still bound it.
- The grouped card is a new UI in both apps. A person reading three lines
  is the point, so the limit stays small (🔧 3).
- Pending actions on stale targets become more common, so `superseded`
  (TODO 23) has to land first.
- The handle map makes the model's prose less specific ("person_2"). The
  UI and the draft page show real names, where a person reads them.

## Alternatives considered

- **Split routes** (`/move` and `/resolve`). This changes the console's API
  for an agent concern and duplicates the lifecycle's checks. Rejected.
- **Tools restricted in ai-engine.** Enforces nothing (see Context).
  Rejected.
- **One "apply all" route for a group.** A new kind of consent, and a
  partial failure would have to be all-or-nothing or explained. Rejected for
  independent applies.
- **Names in tool results.** Names reach a hosted model provider and are
  unnecessary for the choice. Rejected for handles.
- **Scheduled agents with a service identity.** Reverses ADR-0046 §3.
  Rejected. Digests stay code-built (F10's weekly email, F1/F4's SLA
  warnings).
