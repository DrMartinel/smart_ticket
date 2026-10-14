# ADR-0023: The requester answers the clarifying question

**Status:** Proposed
**Date:** 2026-10-12
**Builds on:** ADR-0016 (the `clarify` branch), and closes its *Not decided*
section for chat tickets
**Touches:** ADR-0001 (the LLM proposes, code decides), spec §5 (masking),
§14 (shadow mode sends nothing), docs/TODO.md item 10

## Context

Since ADR-0016 the router can choose `clarify`: the ticket fits several
shown KB pages and doesn't say which. Nothing could ask the requester, so
every `clarify` became a review item for a person to ask by hand, and in the
chat the requester saw the same "create a ticket?" prompt as for any
handoff. A requester who could have said "the VPN one" in two seconds waited
for a technician instead.

The chat (`apps/chat`, `services/chat`) is a channel back to the requester:
the requester is on the page, polling for the outcome of their question.

## Decision

**A live chat ticket asks its requester the proposed question.** When the
router chooses `clarify` for a chat ticket and shadow mode is off:

1. **The question is shown, the decision stays held.** The ticket waits for
   the requester as any held handoff does (`awaiting_requester`,
   `held_decision`), and a `ticket_clarifications` row records the question,
   its options with their KB page titles, and the run that asked it. The
   chat shows the question, one button per option (the page's title, never
   the slug), a free-text answer, and "talk to a person instead", which
   releases the held decision exactly as before: a review item in the
   `clarification` queue.
2. **The answer is untrusted input, handled like a ticket.** It is masked
   inline with the same two tiers (`mask_reply`); its placeholders continue
   the ticket's numbering, so `[EMAIL_1]` in the answer can't be read as the
   ticket's; its PII is quarantined; the ticket's PII level becomes the worse
   of the two. The masked answer, and not the question, is appended to the
   ticket's masked body as a last line, `Requester clarified: <answer>`,
   which reviewers and the next run read. The question names every reading
   it chose between; appended, it pulled the next run's draft and retrieval
   back toward all of them (TKT-2026-000020: Jev's top score 0.97, then
   0.74). A typed answer that only makes sense beside the question ("the
   second one") loses that context; a tapped option is a page title and
   keeps its meaning.
   **The proposal prompt reads that line** (`propose.v9`, rule 8): the
   reading is chosen, so the model doesn't propose `clarify` again but
   answers under it, routes, or says no excerpt fits. Without it, v8 asked
   again and the round cap sent the ticket to a person.
3. **The pipeline runs again on the whole ticket.** A new `AiRun`, every
   hard gate in order: a password in the answer blocks
   (`pii_critical`), an answer NER can't mask goes to a person
   (`pii_mask_failed`), an injection blocks (`injection_detected`). The
   second run may reach any branch.
4. **One question, then a human.** core-api counts the ticket's questions
   and passes the count to the router in `PolicySignals.clarifications_asked`,
   so `router.py` stays pure. A `clarify` proposal at or past
   `clarification.max_rounds` (1) goes to a person as `clarify_round_cap`,
   in the `clarification` queue, where the question and the answer are in
   the body. `max_rounds: 0` turns asking off.
5. **An unanswered question closes after `clarification.wait_minutes`**
   (60 🔧). The chat then offers a ticket, as for any held handoff, and a
   late answer is refused (409). Nothing goes to support on its own: the
   project owner chose this over sending every abandoned question to a
   person (2026-10-12), so an unanswered ambiguous question is treated like
   any other chat handoff the requester didn't ask for.

**Unchanged:** a form ticket's `clarify`, and any `clarify` in shadow mode,
is a review item as under ADR-0016: a form has no channel back, and shadow
mode sends nothing (spec §14 P1). A security ticket is never asked
(`clarify_security`, ADR-0016). ai-engine and its wire schema don't change:
the second run is an ordinary analysis of a longer ticket.

## Why it is safe for an LLM-written question to reach a requester

The question is the first LLM text a requester sees that no approved KB page
backs and no person has read. What bounds it:

- **It asks, it doesn't answer.** It carries no KB text as an answer and
  grants or changes nothing; what the requester does next goes through every
  gate again.
- **Every hard gate passed first.** Injection, critical PII, mass incident,
  mask failure, the retrieval floor and the schema all run before `clarify`
  is possible (ADR-0016).
- **Its options were checked.** Two or more distinct slugs among the chunks
  the model was shown (`clarify_options_in_topk`); the buttons show those
  pages' titles from the KB, not text from the model.
- **Its length is capped** at 300 characters by the proposal schema.
- **Never on a security ticket, never twice.**

The residual risk is the question's wording: a misleading or odd question,
shown once, in a chat that says it is an assistant. That is accepted here;
the `ticket_clarifications` rows are the data to judge it by.

## Consequences

- A new table, `ticket_clarifications`, and a `PolicySignals` field with a
  default of 0 for stored signals (rule 4); web and chat types regenerated.
- `ReasonCode.CLARIFY_ROUND_CAP`; `ChatState.CLARIFY`;
  `POST /api/chat/tickets/{id}/clarify`.
- `thresholds.yaml` gains `clarification.max_rounds` and
  `clarification.wait_minutes`.
- An answer can only raise a ticket's PII level, never lower it.
- The same value in the ticket and the answer gets two placeholders: the
  ticket's raw values are not kept to compare against.
- The second run costs a second analysis (draft, retrieval, Jev, proposal).
- An abandoned question reaches no one unless the requester asks: an
  ambiguous ticket can be dropped by a requester who closes the tab, as any
  held chat handoff can.
- The golden set is single-turn: no eval measures the second run yet, so
  `propose.v9`'s rule 8 is unmeasured; on single-turn tickets v9 should
  score as v8 did.
- A requester can type "Requester clarified:" into a ticket themselves.
  The most it does is stop the model proposing `clarify`; every other gate
  is unchanged.

## Amendment (2026-10-13): code builds the options, the question is fixed

**What changed.** The buttons were the LLM's `proposed_options`, titled
from the KB. The same ticket got different options run after run: "I forgot
my password, how do I reset it?" offered 5 different option sets in 5 runs,
and in two of them, and in all three runs of g154, Jev's top 5 was
identical: the model chose differently from the same pages
(`evals/HISTORY.md`, ADR-0024's outcome). Its question also named readings
the buttons didn't offer ("Windows, macOS, or Linux" above two buttons).

1. **core-api builds the options** (`Clarifications.options`, pure): each
   distinct page of Jev's top 5, in Jev's order, scoring within
   `clarification.option_margin` (0.1 🔧) of Jev's best, at most
   `clarification.max_options` (5), active pages only. The owner's choice
   the same day, after a 0.2 margin (which offered administrator pages)
   and a fixed 0.8 bar (which asks nothing when Jev is unsure of every
   page): on 13 live runs (11 and 2) 0.1 offered "VPN not working" exactly the
   Windows and macOS clients, and "I forgot my password" the portal, root
   and, when retrieved, WorkSpaces pages. A threshold on Jev's
   scale (ADR-0005). The same top 5 now always gives the same buttons.
2. **The question is fixed**: "Which of these is closest to what you need?"
   The model's own question stays in `ai_runs.proposed_draft`.
3. **"None of these"** opens the free-text answer, so a reading the buttons
   miss is one tap away; the text box is hidden until then.
4. **Fewer than 2 pages within the margin: nothing is asked.** The clarify
   decision is carried out as for a form ticket, a review item in the
   `clarification` queue.

The LLM still decides *whether* to ask (it proposes `clarify`, and the
validator still requires its options to be among the pages shown), and that
decision still varies between runs. The top 5 itself varies with the draft.

## Amendment (2026-10-14): Jev scores each page for the buttons

**What changed.** On Jev's choice scale (ADR-0026) one passage takes almost
all the probability even when the ticket is ambiguous ("I forgot my
password": portal 0.91, root 0.05), so "within `option_margin` of Jev's
best" offered two pages on 4 of 28 clarify tickets. Rewording the choice
question didn't change that (2026-10-14 probe: 0/22 tickets with two right
readings, three wordings).

1. **Jev scores each page** when the LLM proposes clarify and the validator
   passes its options: `ScoreOptionsNode` asks Jev the yes/no question
   (`CLARIFY_OPTION_QUESTION_VERSION=rerank_resolves.v1`) for each chunk of
   the top 5, in parallel. Every other ticket makes no such request. A
   failure raises: `ai_engine_unavailable`, as for any Jev failure.
2. **The buttons come from those scores**: `retrieved_chunks[].option_score`.
   `Clarifications.options` keeps its rule (within 0.1 🔧 of the best, at
   most 5), now on the yes/no scale it was chosen on; a chunk without a
   score offers nothing.
3. **Measured** on the 28 clarify tickets: 2+ buttons on 16 (4 before);
   buttons covering two right readings on 3 of 22, of the 6 whose top 5
   held two. Jev's yes/no scores for the same page varied by 0.01 (median)
   across three runs; most run-to-run change in the buttons comes from the
   top 5 itself, which the draft varies.

The LLM still decides whether to ask; code still decides what is offered.
The bigger limit is retrieval: only 6 of 22 tickets had two right readings
in the top 5.
