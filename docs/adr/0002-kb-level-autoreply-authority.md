# ADR-0002: Auto-reply authority lives on the KB article, not on LLM intent

**Status:** Accepted
**Date:** 2026-07-27

## Context

`AutoReplyProposal.proposed_intent == "auto_reply"` tells you the model
*wants* to send a canned answer. It says nothing about whether that KB
article is safe to send automatically. Someone will eventually propose
reusing `proposed_intent` directly as the auto-reply gate, because adding a
separate authority field feels redundant — "the model already said
auto_reply, why check something else?"

## Decision

`kb_articles.auto_reply_allowed` is the only source of auto-reply
authority. It is:

- `false` by default on every new article,
- settable only by a `manager`-role user with a logged reason
  (`kb_authority_log`),
- constrained at the database level: `CHECK (auto_reply_allowed = false OR
  approved_by IS NOT NULL)` — the flag cannot be true without an
  identifiable human approver.

`router.py` checks `kb.auto_reply_allowed` before ever looking at
`proposal.root.proposed_intent`. If the KB article isn't authorized, the
ticket goes to HITL regardless of how confident the model's proposal looks.

## Consequences

- A model cannot grant itself permission to auto-reply by simply proposing
  `auto_reply` more often or more confidently.
- Rolling out auto-reply is a KB governance action (flip a flag on 3-5
  low-risk articles, per the P4 rollout in spec §14), not a prompt or
  threshold change — it stays visible and auditable to whoever owns KB
  content.
- Extra indirection: every `AutoReplyProposal` needs a KB lookup before
  it can be trusted. This is the point, not overhead to optimize away.
