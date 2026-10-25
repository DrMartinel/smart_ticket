# ADR-0036: KB drafts live outside `kb_articles`; a text change revokes authority

**Status:** Proposed (phase 2 pack, stage 3; copied 2026-10-17, awaiting the owner's decision)
**Date:** 2026-10-17
**Builds on:** ADR-0002 (authority on KB rows), ADR-0027, ADR-0004 / ADR-0025 (ai-engine grants)
**Feature:** F6 ([spec](../requirements/phase-2/06-F6-kb-governance.md))

## Context

Pages are created live (`create_and_ingest`). F6 adds review before publish.
A draft must never reach retrieval. ai-engine reads `kb_articles` and
`kb_chunks` with `is_active = true` in three queries. Separately, an edit to
a page keeps `auto_reply_allowed`, so a manager's approval of old text
covers new text. Only the demo loader re-checks, with SHA-256 pins.

## Decision

1. **Drafts are rows in a new `kb_drafts` table**, not a status on
   `kb_articles`. ai-engine's code and grants don't change, and no filter
   can be forgotten.
2. **Publishing copies an approved draft into `kb_articles`** and ingests
   with the existing indexer. It never grants authority.
3. **A published change to title or body, or a retirement, revokes
   `auto_reply_allowed`** in the same transaction, with a `kb_authority_log`
   row. Any publisher may revoke; only a manager grants (ADR-0002 unchanged).
4. **A grant pins the SHA-256 of the text the manager saw**
   (`approved_text_sha256`). core-api treats a page whose text hash differs
   as not authorized when building the router's `KBArticleMeta`.
   `router.py` stays pure.

## Consequences

- Authority always refers to the text that was read, for every page, not
  only the demo snapshot.
- An edit to a popular low-risk page sends its tickets to people until a
  manager re-grants. That's intended: the authority queue makes it visible.
