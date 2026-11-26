# ADR-0050: The agent asks for context; the branch picks the workflow path

**Status:** Proposed (2026-11-26), the owner's direction. Not built: it waits on the measurements in decision 8.
**Date:** 2026-11-26
**Will supersede, once accepted:** ADR-0016 (the `clarify` branch), ADR-0023 (the requester answers the clarifying question)
**Builds on:** ADR-0001 (the LLM proposes, code decides), ADR-0006 (runbooks always go to a human), ADR-0028 (configurable workflows), ADR-0034 (chat memory), ADR-0035 (per-branch rollout), ADR-0046 (the agent acts as the user), ADR-0049 (categories as rows; part 3, a workflow per category)
**Touches:** spec §8 (the router's branches), docs/TODO.md items 10, 23 and 26

## Context

Two mechanisms ask a requester for more context.

- **The `clarify` branch** (ADR-0016, ADR-0023). The model may propose
  `clarify` only when two or more of the shown KB pages each answer a
  different reading of one problem. core-api builds the buttons from Jev's
  yes/no score per page. One question is asked, and a second goes to a
  person. A form ticket, or any ticket in shadow mode, becomes a review item
  instead.
- **The agent** (ADR-0046). It talks with the person over several turns and
  asks in its own words. On the chat it calls the helpdesk (`ask_helpdesk`),
  which runs triage, and relays a `clarify` question through
  `answer_clarification`.

On the chat, the two are stacked: the agent asks the helpdesk, the helpdesk
asks a question, and the agent passes it on. The branch also covers only one
kind of missing context, which page is meant. It cannot ask for a detail
such as which server.

On `smart_triage` (the shadow pilot, 2026-11-26):
- 19 of 248 routing decisions were `clarify`;
- 179 of 245 tickets came through the chat;
- there were 22 agent turns, and 15 of them replied.

The branch already decides where a ticket enters its workflow. Each branch
moves the ticket into its own pipeline status (`auto_replied`,
`auto_routed`, `pending_review`, `blocked`, `escalated`), and a workflow
action can already start an n8n workflow when a ticket enters a status
(`trigger_n8n`, ADR-0028). Three things are missing:
- a decision that this is the branch's job;
- the fields an n8n flow needs;
- a rule for flows that change systems.

## Decision

1. **The agent gathers context, and the `clarify` branch goes.**
   - When the helpdesk can't answer, the agent asks the person follow-up
     questions in its own words, then asks the helpdesk again with what it
     learned.
   - The new question carries the earlier ones as chat memory (ADR-0034).
   - The model no longer proposes `clarify`: a new propose version drops
     shape (e). A ticket that fits several pages is `insufficient_context`,
     and the proposal says what is missing.
2. **The agent sees what is missing.** When triage ends in
   `insufficient_context`, the chat turn the agent reads carries the model's
   missing-information text. On the wire it becomes
   `proposed_missing_information`, since the LLM wrote it. The agent words a
   question from it; it decides nothing.
3. **Code still decides.** The agent's questions only improve the input.
   - Every answer goes through triage and `router.py` again.
   - The agent never approves its own answer.
   - A security question is never held for more context: Jev's `security`
     category goes to a person at once, as `clarify_security` does today
     (ADR-0016).
4. **The requester sees three outcomes** (the chat states):

   | Outcome | When |
   |---|---|
   | Answered | `auto_reply` |
   | Suggest a ticket | The agent can't help or can't find the context (an agent hand-off), or triage sends the question to a person or a team (`hitl`, `auto_route`) |
   | With support | Masking failed, a mass incident (`escalate`), a blocked message (`block`: an injection or a password), or a security question (decision 3) |

   The `clarify` chat state goes.
5. **Five branches pick the workflow path:** `auto_reply`, `auto_route`,
   `hitl`, `block` and `escalate`.
   - A branch decides which status the ticket enters; the mapping is
     unchanged.
   - Together with the ticket's fields, the branch decides which workflow
     actions run there. ADR-0049 part 3 adds the category's own workflow.
   - A form ticket the model finds ambiguous goes to a person (`hitl`), the
     way every unclear case degrades.
6. **n8n flows start from the branch.**
   - A workflow admin attaches `trigger_n8n` to a branch's status.
   - The fields an action can send gain `ticket.branch`,
     `ticket.reasonCode` and `ticket.priority`.
   - A flow that only notifies, adds information or opens a vendor ticket
     may start from any status.
7. **An automatic branch never starts a flow that changes a system**
   (an account, a server, a network).
   - Such a flow starts only on a move a person made, or after a person
     confirms it.
   - This extends ADR-0006 from runbooks the model proposes to flows a
     branch starts.
   - How an action is marked as changing a system is open question 2.
8. **Measure before building.** The `clarify` branch is removed only after
   two things.
   - **The agent has been run.** Its end-to-end trace suite
     (`evals/suites/test_agent_traces.py`) and `agent.v2` have run against a
     real model. Neither has run yet.
   - **Auto-reply precision holds.** An eval run of the new propose version
     shows auto-reply precision at or above its floor. ADR-0016 added
     `clarify` because ambiguous tickets were auto-replied with a guess
     (g151, g155). Without shape (e) they must become
     `insufficient_context`, not auto-replies. Two later gates, Jev's
     confidence bar (`retrieval.min_rerank_confidence`, 0.9) and the check
     that the cited page is Jev's choice, may now catch most of them. That
     has to be measured, not assumed.

## Consequences

- **Removed, once built:**
  - the `clarify` branch and its reason codes (`clarify_security`,
    `clarify_options_not_shown`, `clarify_round_cap`);
  - `ClarificationProposal` in both services, in one PR (hard rule 4);
  - `GenerationSignals.clarify_options_in_topk`;
  - ai-engine's `score_options` node and Jev's `rerank_resolves` question;
  - core-api's `Clarifications` service and the `clarification`
    thresholds block;
  - the `clarification` review queue;
  - the chat's clarify buttons;
  - the agent's `answer_clarification` tool.
- **Kept, with less to do:**
  - The `requester_questions` rollout flag keeps its other job: holding a
    chat decision until the person asks for a ticket.
  - Rollout, reports, calibration and the eval gates keep reading the
    branch.
- **What changes for people:**
  - A form ticket that fits several pages reaches a person instead of
    prompting a question. Forms have no way to answer back, so this was
    already a review item before ADR-0023.
  - The agent's prompt gains a rule: when the helpdesk says what is
    missing, ask the person for it. Its asking is capped per conversation
    (open question 3).
- **Golden set:** the `clarify` golden cases are relabelled. A form ticket
  expects `hitl`; a chat ticket's expected path is the agent asking.
- **Accepted risk:** a question the agent words is LLM text that reaches
  the requester. So is today's relayed `clarify` question, and the agent's
  replies are already shown unedited (ADR-0046).

## Open questions

1. What bar the agent's eval must clear before `clarify` goes. No agent eval
   has run, so there is no baseline yet.
2. How a `trigger_n8n` action is marked as changing a system:
   - a flag the workflow admin sets, which core-api then refuses on a
     status the pipeline moves tickets into; or
   - every n8n flow treated as changing unless it is marked read-only.
3. How many times the agent may ask the helpdesk in one conversation before
   it offers a ticket: a number in `thresholds.yaml` `agent:`.
4. Whether `ticket_clarifications` is dropped or kept read-only for the
   questions already asked.
5. Whether a workflow can choose its actions by a ticket's built-in fields
   (category, priority, source), beyond ADR-0049 part 3's per-category
   workflow, or n8n branches on them itself.

## Alternatives

- **Keep both, with the agent relaying the helpdesk's question.** Two
  mechanisms for one job, and `clarify` still covers only "which page".
- **Keep `clarify` for form tickets only.** A form can't answer back, so it
  is a review item anyway, and a person asking is the same as `hitl` with
  the missing information shown.
- **Let the agent decide the outcome when it is confident, skipping
  triage.** The agent would approve its own answers, which ADR-0001 rules
  out.
