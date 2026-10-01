# ADR-0014: Expand retrieval candidates through article associations, and let an LLM re-order chunks above the floor

**Status:** Proposed. The experiments below support it; three checks listed
under *Before this is accepted* have not run.
**Date:** 2026-10-01
**Builds on:** ADR-0005 (thresholds compare the cross-encoder score only), ADR-0013 (pg_search BM25)
**Touches:** ADR-0001 (code decides, the LLM proposes), ADR-0004 (ai-engine's read-only role)

## Context

Retrieval recall @3 is 0.767 on `main` (`003f7d3`): the top `rerank_top_n`
(3) chunks by cross-encoder score reach the classify model, several from one
article allowed. One chunk per article (`a890eb7`) was tried and reverted,
because several chunks of an article are wanted as context. The 14 misses
are mostly tickets that
describe a **symptom** while the page that answers them is named after the
**cause or the fix**: "SES only sends to verified addresses" against
*Request production access (Moving out of the SES sandbox)*; "Backdoor finding
for our bastion host" against *Remediating a potentially compromised EC2
instance*, a page that never contains the word "Backdoor". Embeddings, BM25
and the cross-encoder all match wording, not cause and effect.

A series of probes measured where that gap can be closed, on the full golden
`kb_covered` set (60) and, where refusal could move, the `out_of_kb` set (23).
The expansion and re-ordering probes ran ai-engine's own `hybrid_retrieve` and
`rerank` nodes in-process against the live stack, and each reproduced
production's recall before changing anything. They ran twice: first with one
chunk per article as production (2026-10-01), then, after the revert, on
multi-chunk retrieval (2026-10-01 (2)). The article-first and Laya probes
ran only in the first round; neither result depends on the difference. The
article-first probe was a dense-only prototype (no BM25), so its losses are
partly that. Details and configuration: `evals/HISTORY.md`.

| Probe | recall@3, multi-chunk (**production**) | recall@3, one chunk per article | Lost | Verdict |
|---|---|---|---|---|
| Production | **0.767** (14 misses) | 0.783 (13 misses) | — | baseline |
| Articles first, then chunks within the top N articles (dense stage 1) | — | 0.717–0.767 | 3–6 | rejected: the gold article ranks 17–1,035 for 9 of 13 misses under every article representation |
| **+ pages linked from the articles of the reranked top 3** (authored Markdown links) | **0.800** (+2) | 0.850 (+4) | **0** | works; KB-specific |
| + links, re-ordered by Laya zero-shot (`laya-multilingual`) | — | 0.633–0.717 | 8–17 | rejected |
| **+ links, top 8 above the floor re-ordered by Qwen3-8B, both presentation orders must agree** | **0.850** (+5) | 0.883 (+6) | **0** | works |
| Same re-ordering on production's candidates (no expansion) | 0.767 | 0.783 | 0 | no effect |
| `rerank_top_n` 5 instead of 3 | — | 0.783 (any per-article rule) | 0 | no effect: misses rank 6th or lower |

Three findings explain the table:

1. **The fix page is usually one association away.** For 9 of the 13 misses
   (one chunk per article), the gold page is linked from a page production
   already retrieves. Following those links recovers 4 of them (2 of 14 on
   multi-chunk retrieval, where the top 3 spans a median of 2 articles, so
   there are fewer pages to follow links from), and no other ticket is lost. Out-of-KB
   refusal is unaffected: none of the 23 out-of-KB tickets clears
   `retrieval.floor` (0.45) with or without expansion (highest top-1 score
   0.098 → 0.101).
2. **Then the cross-encoder is the ceiling.** In 5 of the 6 linked misses that
   expansion does not recover, the gold chunk is in the pool and scores
   0.40–0.72, well above the floor, but loses to pages that describe the
   symptom (0.42–0.97). The cross-encoder judges whether a passage is *about*
   the ticket, not whether it *resolves* it. Chunk selection is not the
   problem: the gold page's best chunk was always among those added.
3. **A generative LLM can make that judgement; a zero-shot encoder cannot.**
   Asked which passages resolve the ticket, Laya separates the gold page from
   the rest worse than the cross-encoder (AUROC 0.59–0.64 against 0.81–0.84;
   gold first for 20 of 55 tickets against 38): it scores almost every relevant
   page 0.70–0.88. Its model card warns the base checkpoints are near chance
   until fine-tuned. Qwen3-8B, the model `vllm-chat` already serves, recovers
   cases expansion alone does not: g036, g058 and g060 on multi-chunk
   retrieval (g050 and g052 with one chunk per article). It is
   position-biased (its first pick agrees across the two presentation orders
   for only 28–35 of 58–59 tickets), and shown the passages in reverse it
   loses 1–5 cases; requiring both orders to agree keeps the gains and loses
   none, in both rounds.

## Decision (proposed)

**1. An article-associations layer feeds candidate expansion.** Each
association links an article to other articles, tagged with its `source` and
whether it has been reviewed. The first source is `authored_link`: Markdown
links extracted from chunk text at ingestion (relative links resolve within
the guide; absolute ones by page name only when that name is unambiguous).
Sources that work on a KB without links are added only once they pass the same
probe (see *Open*).

**2. Expansion seeds from the articles of the reranked top 3 chunks.** Associated articles not already
among the candidates contribute their best chunks by embedding similarity
(5 in the probe), with a cap on associations followed per seed (one page links
to 198 others). Seeding from all ten candidates doubled the cost (median 130
chunks reranked against 67) and recovered nothing more.

**3. The cross-encoder scores every candidate, original and added, and stays
the only input to the floor and to the trust signals** (ADR-0005).
`rerank_top1`, `rerank_margin`, `docs_above_floor` and `RerankNode.decide()`
read the **cross-encoder order**, before any re-ordering, so refusal-before-LLM
and the trust score cannot be moved by step 4.

**4. Optionally, an LLM re-orders the chunks that clear the floor.** It sees up
to 8 such chunks, several from one article allowed, as production passes
them, and returns an ordering, never a score:
- structured output whose items are an enum of the passage ids shown, checked
  to be an exact permutation (vLLM's grammar has no `uniqueItems`);
- run twice, with the passages in cross-encoder order and reversed; a chunk is
  promoted into the top `rerank_top_n` only when both runs place it there, and
  the remaining slots follow cross-encoder order;
- any failure (invalid output, timeout, unavailable model) falls back to
  cross-encoder order, logged, never to an empty result;
- the prompt frames the ticket and passages as data, and the prompt file is
  versioned and eval-gated like `classify`.

**5. Zero-shot Laya is not used.** A fine-tuned checkpoint could be
reconsidered once human-confirmed (ticket, passage, resolves?) labels exist
from shadow mode. The golden set must never be its training data (rule 9).

## Rationale

Widening the candidate pool does not scale: as the KB grows, the fix chunk has
to beat more chunks to be seen. Associations bring the fix page in by its
relationship to what was found, whatever the KB size. Keeping the cross-encoder
as the scorer keeps `retrieval.floor` calibrated (ADR-0005) and keeps refusal
deterministic. The LLM's role is narrow: it chooses which already-relevant
pages the classify model sees, it cannot add a page, and it cannot change a
score. An ordering with an enum schema is about the smallest authority an LLM
output can carry.

The two-order agreement is what makes that authority acceptable. A single
ordering partly reflects the order the passages were shown in; promoting a page
only when it wins regardless of presentation turns a fragile preference into a
consistent one, at the cost of a second call.

## Alternatives considered

- **Raise `fusion_candidate_limit` / `vector_top_k`.** Grows with the KB and
  still ranks by wording; measured indirectly by the article-first probe, where
  the gold article ranked 17–1,035.
- **Retrieve articles first, then chunks within them.** Measured: 0.717–0.767,
  below production, at 4–11 times the reranker cost.
- **An LLM reranker that produces relevance scores.** Its scores would replace
  the cross-encoder's as the floor input, an uncalibrated distribution that
  ticket text can try to steer. Rejected in favour of ordering only.
- **Zero-shot Laya** (open-weights System 1 decision model). Measured above.
- **Full GraphRAG** (LLM-extracted entity graph, communities, summaries).
  Its summaries can't be answer text (auto-reply quotes approved KB text
  only, ADR-0002), and its graph is too large to review. A per-article
  entity-extraction variant is the candidate KB-agnostic association source
  (see *Open*).

## Consequences

- **New authority for an LLM**, bounded as above: the re-orderer decides which
  KB passages, among those above the floor, the classify model sees. Auto-reply
  authority stays on KB rows (ADR-0002), quotes are still validated against the
  passages shown, and `router.py` decides every branch.
- **Latency and GPU.** Expansion raises the reranker batch from 10 to a median
  of 48 chunks (162 at most) on multi-chunk retrieval. Re-ordering adds two
  chat calls per ticket, 1.39 s p50 / 2.44 s p95 each on the shared GPU, on
  the same `vllm-chat` as classification.
- **Context budget.** `vllm-chat` serves 4,096 tokens; eight passages had to be
  cut to fit 308 times in the multi-chunk probe. A cut can remove the fix
  text. The re-orderer needs an explicit token budget in settings.
- **Storage.** Associations need a table core-api writes at ingestion and
  ai-engine reads, which means a `SELECT` grant for `ai_engine_ro` (ADR-0004).
  Extracting links per request from chunk text would avoid the table but
  repeats the work on every ticket.
- **Settings.** Seeds, chunks per associated page, the association cap, chunks
  re-ordered and the token budget are ai-engine `Settings` (operational, not
  calibration); none is a threshold.

## Before this is accepted

1. **Full eval run** with expansion and re-ordering: auto-reply precision
   (currently 0.95, exactly at its floor), branch accuracy and the refusal
   suite, not only recall. Re-ordering changes which chunks the classify model
   quotes.
2. **Injection check:** the 15 injection tickets through the re-orderer, to
   confirm none of them changes which chunks it promotes.
3. **A KB-agnostic association source**, measured against `authored_link` on
   this KB with the links withheld: embedding neighbours between articles (no
   LLM) as the baseline, then per-article entity extraction (GraphRAG-lite).
   Without one, decision 1 only helps KBs that link their pages.

## Open

- The evidence is +2 and +3 cases on multi-chunk retrieval (+4 and +2 with
  one chunk per article), on a synthetic golden set of 60, one run each. It
  shows a mechanism, not a production estimate.
- One chunk per article was worth 2–3 cases *inside* this pipeline, more than
  its single case alone: on multi-chunk retrieval the top 3 spans fewer
  articles to expand from, and one article's chunks can take the slots a
  linked page needs. Whether expansion caps chunks per article within its own
  pool, while production still passes several chunks of an article to the
  model, is open.
- g048 ("SES sending limit too low") may have more than one correct page;
  it belongs in the multi-gold review, not in these numbers' favour.
- 2 of the 13 misses (g011, g012, `troubleshoot_access-denied`) are not
  reachable within two links, and g008 is unreachable under strict link
  resolution. Associations do not cover everything.
