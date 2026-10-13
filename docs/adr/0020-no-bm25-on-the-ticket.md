# ADR-0020: No BM25 on the ticket; the keyword-agreement trust feature is removed

**Status:** Proposed
**Date:** 2026-10-11
**Supersedes:** ADR-0013's use of BM25 on the ticket, in retrieval and as the
`bm25_keyword_hit` trust feature. ADR-0013's choice of pg_search and its
index stand.
**Touches:** ADR-0005 (what may be thresholded), ADR-0003 (the trust score's
features), spec §6.3 (hybrid retrieval), spec §4.4 (`bm25_keyword_hit`)

## Context

Retrieval fused two lists, BM25 and vector search, both run on the ticket.
On the 500-ticket golden set (`evals/HISTORY.md` 2026-10-11), BM25 was the
weak one: it placed the gold page in its top 10 pages for 57% of tickets
against vector search's 81%, and fusing it in gave about 79%, below vector
search alone. A ticket describes symptoms in the requester's words; the page
that fixes it names features and settings. Keyword matching on the ticket
mostly matches the wrong vocabulary.

BM25 on the ticket also fed `bm25_keyword_hit`, a hand-set trust feature
(weight 0.5): Jev's top article within BM25's top `keyword_agreement_k`
articles. With BM25's ranking weak, its agreement is weak evidence too.

## Decision

1. **Retrieval does not run BM25 on the ticket.** Candidates come from vector
   search on the ticket through RRF (a single list today; fusion takes a list
   of ranked lists, so other lists can join it), then the first
   `FUSION_CANDIDATE_LIMIT` pages, one chunk each.
2. **`bm25_keyword_hit` is removed** from the trust score, the trust model
   (`trust_model_v0.json`, new `model_version`, intercept unchanged), the
   `RetrievalSignals` wire field `bm25_rank_of_top1` in both services, the
   reviewer panel and `thresholds.yaml` (`retrieval.keyword_agreement_k`).
   The wire field is dropped rather than defaulted: no stored rows carry it
   (the user's decision).
3. **`BM25_ERROR_CODE_BOOST` and `RRF_BM25_WEIGHT` are removed.** Both only
   applied to BM25 on the ticket.
4. **pg_search, its index and `bm25_search` stay,** for searching text written
   in the KB's own vocabulary (measured on drafted answers, 2026-10-11).

## Consequences

- Retrieval is vector-only on the ticket. Exact error codes and product names
  in a ticket no longer get a keyword match of their own; the embedding has
  to carry them.
- Trust scores fall by up to the feature's weight for tickets where BM25 used
  to agree with Jev. The coefficients are a hand-set prior and SHADOW_MODE
  routes every ticket to a person, so no ticket is auto-handled differently
  today; recalibration (spec §7.1) fits the remaining features.
- `CLAUDE.md`'s gotcha about catching a BM25 error no longer applies to
  retrieval: there is no BM25 query on the ticket to fail. A pg_search
  misconfiguration still fails `migrate`.
- The retrieval suite and a full run must be re-run and recorded, as for any
  retrieval change.

## Alternatives considered

- **Down-weight BM25 in fusion (`RRF_BM25_WEIGHT` 0.5).** Measured offline
  only: more gold pages among the candidates (406 against 381 of 500), never
  end to end. Removed with BM25 on the ticket.
- **Keep BM25 on the ticket for the trust feature only.** One cheap query per
  ticket keeps the trust score as it was; declined in favour of removing the
  ticket's keyword channel entirely.
