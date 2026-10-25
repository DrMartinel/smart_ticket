# ADR-0034: A chat conversation gives the model its earlier masked turns

**Status:** Proposed (phase 2 pack, stage 2). Moved to [`docs/adr/0034-conversation-context-for-the-model.md`](../../../adr/0034-conversation-context-for-the-model.md); its status there is the one that counts
**Date:** 2026-10-17
**Builds on:** ADR-0001, ADR-0003, ADR-0023 (requester answers the clarifying question)
**Feature:** F3 ([spec](../06-F3-requester-chat.md))

**This relaxes a guardrail.** Today each ticket is analysed alone: ai-engine
sees only that ticket's masked subject and body. After this ADR it also sees
up to six earlier masked turns of the same chat conversation.

## Context

In the chat, people ask follow-ups ("did that, still failing, I'm on 4G").
Analysed alone, a follow-up has no subject; retrieval and the proposal guess.
The owner asked for memory across turns within one conversation and none
across conversations.

## Decision

1. `TicketMasked` gains `prior_turns` (default empty), defined in both
   services in the same PR (ADR-0010, CLAUDE.md rule 4).
2. Prior turns are **masked text the system already stored**, from the **same
   conversation and the same requester**, at most six, and a conversation
   ends after 30 minutes idle.
3. **A turn that was blocked or `mask_failed` ends the conversation.** Its
   text can never become context.
4. Prior turns feed only the HyDE draft and the proposal prompt. They are not
   a trust signal, not a router input, and every hard gate runs on the new
   ticket exactly as before. A test pins that the router's decision is the
   same with and without them for the same signals.
5. Prompt versions bump and pass the eval gate, including new multi-turn
   cases reviewed by someone other than their author.

## Why this is safe

- Nothing raw reaches the model that didn't before: every prior turn passed
  inline masking and injection detection when it was submitted.
- Authority doesn't move: the model can propose better, not decide more.
- Scope is narrow: one person, one conversation, a short window.

## Consequences

- Better follow-ups; slightly longer prompts (≤ 6 short turns).
- A new failure path to test: prior-turn assembly failing → the ticket is
  analysed alone and the conversation ends (degrade toward the old behaviour).
