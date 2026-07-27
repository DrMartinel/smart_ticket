# ADR-0005: Retrieval thresholds apply to the cross-encoder score, never the RRF fusion score

**Status:** Accepted
**Date:** 2026-07-27

## Context

This is a technical trap, not a philosophical one, and it is easy to fall
into during a refactor: `thresholds.yaml` has `retrieval.floor: 0.45` right
next to `retrieval.rrf_k: 60`, in the same `retrieval:` block. A future
refactor of `ai-engine/graph/nodes/rerank.py` or `retrieve.py` could
plausibly move the floor check earlier, against the RRF-fused score, and
nothing would immediately look wrong — the code would still run, the graph
would still route somewhere.

## Decision

`retrieval.floor` and `retrieval.margin` are checked **only** in
`ai_engine/graph/nodes/rerank.py`, against `reranked[0].score` (the
cross-encoder's output), never against the RRF score computed in
`retrieval/fusion.py`.

## Rationale

Reciprocal Rank Fusion produces a *rank-based* score:
`score(d) = Σ 1 / (k + rank_i(d))`. Its absolute magnitude has no
independent meaning — it depends only on how many rankers contributed and
where a document placed in each, not on how relevant the document actually
is. A threshold on it would be comparing apples to a made-up unit.

The cross-encoder's score, by contrast, is a calibrated relevance judgment
over the (query, chunk) pair — it is meaningful in absolute terms, which is
exactly the property a floor/refuse decision needs.

## Consequences

- `ai_engine/retrieval/fusion.py` should never expose its output as
  something a threshold gets compared against; keep it typed as a ranking
  input only (e.g. return ordered candidates, not a "score" field consumers
  might reach for).
- Code review checklist item: any PR touching `retrieve.py`, `fusion.py`,
  or `rerank.py` should be checked against this ADR specifically, since the
  bug this prevents does not fail loudly.
