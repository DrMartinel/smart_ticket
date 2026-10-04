# ADR-0016: A `clarify` branch, so an underspecified ticket gets a question instead of a guess

**Status:** Proposed. The decision path is implemented and measured; how the
question reaches the requester, and what happens with the answer, is not
decided here (*Not decided*).
**Date:** 2026-10-04
**Builds on:** ADR-0001 (code decides, the LLM proposes), ADR-0002 (auto-reply
authority lives on KB rows), ADR-0006 (runbooks always go to a human)
**Touches:** spec §8 (the router's branches), docs/TODO.md item 10

## Context

Some tickets have a plausible answer in the KB but leave out the detail that
says which answer applies. g151 ("I forgot my password, how do I reset it?")
fits the AWS access portal page, the IAM console password pages and the
WorkSpaces client page; g155 ("The client app keeps crashing on my laptop.")
fits the AWS VPN Client and the WorkSpaces client. In every full run on
2026-10-04 the pipeline auto-replied both with one guess, and they are the
only false auto-replies left: auto-reply precision 0.931 (27/29) against its
0.95 floor (`evals/HISTORY.md`, 2026-10-04 (3)).

The router's branches can only guess (`auto_reply`) or hand the ticket on
(`auto_route`, `hitl`, `escalate`, `block`). The LLM's one honest exit,
`insufficient_context`, reaches a human without saying what to ask, and the
classify prompt reserves it for tickets the KB can't answer at all.

## Decision

A fifth proposal and a sixth branch.

**The LLM may propose a question.** `classify.v6` adds:

```json
{"proposed_intent": "clarify",
 "proposed_question": "<one question that tells the options apart>",
 "proposed_options": ["<kb_slug>", "<kb_slug>"],
 "proposed_category": "<hardware|software|network|access|security|other>",
 "rationale": "<why the ticket does not say which applies>"}
```

The prompt allows it only when two or more of the shown excerpts would each
answer a different reading of the ticket. `proposed_options` must be slugs it
was shown.

**ai-engine checks the options; it decides nothing.** The validator sets a new
`GenerationSignals.clarify_options_in_topk`: true only for a `clarify`
proposal whose options are two or more distinct slugs of the reranked chunks
the model saw. Like every check, its default reads as failed.

**`router.py` decides, after every hard gate.** Injection, critical PII, mass
incident, `mask_failed`, the retrieval floor and the schema check all run
first, unchanged. Then, for a `clarify` proposal:

| Condition | Branch | ReasonCode |
|---|---|---|
| `proposed_category` is `security` | `hitl` | `clarify_security` |
| options not all shown, or fewer than two | `hitl` | `clarify_options_not_shown` |
| otherwise | **`clarify`** | `all_checks_passed` |

- **Security never waits on a requester's answer.** Something may already be
  wrong; a human gets it now. A rule, not a threshold, like ADR-0006.
- **No trust threshold.** A question grants nothing, sends no KB text as an
  answer, and changes no system. The trust score was built to price the risk
  of an automatic action, and this branch takes none (below).
- A `runbook` proposal is untouched: it always goes to a human (ADR-0006),
  and a model cannot turn one into a question.

**Until the requester side exists, `clarify` is executed as human review**, in
shadow mode and out of it: a `clarification` review item carrying the
proposed question, for a person to send, edit or ignore. No code sends
anything to the requester. In shadow mode (P1) this is also what the data is
for: technicians' handling of these items is how the branch gets judged.

## Consequences

- An underspecified ticket that used to be auto-replied with a guess is
  routed to `clarify`; auto-reply precision no longer pays for it.
- The wire schema changes in both services (`ClarificationProposal`,
  `clarify_options_in_topk` with a default for stored rows), and the web types
  are regenerated. `Branch`, `ReasonCode` and `ReviewQueue` gain values; the
  `review_items.queue` choices need a migration.
- The LLM gains a new way to avoid committing. If it over-uses it, tickets the
  KB answers go to human review instead of auto-reply: that shows up as lost
  auto-replies and a lower branch accuracy in the end-to-end suite, and as
  `clarify` on `kb_covered` tickets, which must stay rare.
- g151-g156, written as underspecified tickets, are labeled
  `expected_branch: clarify`, reviewed like any golden label (rule 9).

## Not decided

The requester side, for a later ADR before shadow mode ends: a ticket
messages table, how the question is sent, a reply endpoint and view, a
timeout, re-masking the reply (it can carry PII) and re-running the pipeline
on ticket plus answer, a cap on rounds (one question, then a human), and a
`ReasonCode` for each way that fails. Every one of those failure paths goes
to a human.

## Alternatives

- **Let the auto-reply state its assumption** ("If you mean the AWS access
  portal, …"). A prompt-only change, but the requester still gets an answer
  to a question they may not have asked, and precision still counts it as a
  guess.
- **Recalibrate trust on Jev's scale** (TODO item 4), so these fall under
  `t_auto`. Needed anyway, but it can only send the ticket to a human: it
  cannot say what to ask, and a well-calibrated score for "is this page
  relevant" is still high for a vague ticket that the page fits.
- **Treat `insufficient_context` with a question as the clarification.** It
  would mix "the KB has nothing" with "the KB has several things", which
  the dashboard and the refusal suite must tell apart.
