# Recipe: change retrieval (BM25, vector, fusion, rerank)

This is the most dangerous area to change quietly. A mistake here usually shows up
only as a change in how often the LLM is called, or in which chunk it gets. No unit
test turns red.

Open these before writing: `docs/adr/0005-threshold-on-cross-encoder-not-fused-score.md`,
`graph/nodes/retrieve/{node,bm25,vector,fusion}.py`, `graph/nodes/candidate_pool/{node,links}.py`,
`graph/nodes/rerank/node.py`, `graph/nodes/classify_category/node.py` (the floor gate),
`graph/nodes/candidate_pool/shortlister.py`, `graph/nodes/rerank/reranker.py`,
`tests/test_{retrieve,rerank,fusion,db_queries}.py`.

## The ADR-0005 check (mandatory for every change here)

Per CLAUDE.md rule 8, any change touching `graph/nodes/retrieve/`, `graph/nodes/candidate_pool/` or `graph/nodes/rerank/`
has to pass this check, and you should say explicitly that it does:

- [ ] Every threshold comparison uses the **cross-encoder** score, which is
      `RankedChunk.score` after `RerankNode`. Nothing else.
- [ ] Nothing compares a BM25 score (`pdb.score`) with a number either. It is
      query-dependent; only BM25 *ranks* cross into decisions (ADR-0013).
- [ ] Nothing compares an RRF-fused score with a number. `Candidate` has no score
      field, and that absence is deliberate. Don't add one.
- [ ] A slice of the RRF-ordered list (`fusion_candidate_limit`) counts as a
      **limit**, meaning a cost/latency knob. It is not a threshold, and it shouldn't
      be described or tuned as one.
- [ ] `RerankNode` reorders by Jev's score **before** truncating to
      `rerank_top_n`. `decide()` reads `reranked[0].final_score()`, so the order
      decides whether the LLM runs at all.

## Conventions

- Search functions take their inputs and run their reads through `db.all`:
  `def x_search(…) -> list[<Hit>]`, returning frozen pydantic hits. A module that
  reads `db` is listed in conftest's `use_db`.
- Vector search `ORDER BY`s the raw `cosine_distance`, so the HNSW index can serve
  the query. The similarity can be computed in the select list.
- Top-k values, the RRF k and limits all belong in `Settings`, each with a comment.
- Anything that reaches the embedder or reranker comes from masked ticket text only.
- If the embedder or reranker fails, the error propagates. Don't return empty
  candidates (see `test_retrieve.py`).

## Tests

- Build the DB with `fake_db(rows=callable)`, where the callable tells the queries
  apart by their SQL: `"|||" in sql` means the BM25 query (pg_search, ADR-0013). That's how you test a case
  like "lexical found nothing but vector did".
- Add an ordering test that **inverts** the incoming order (see
  `test_rerank.py::test_output_order_follows_the_reranker_not_the_rrf_order`), so a
  dropped sort fails the suite.
- Query-shape tests in `test_db_queries.py` read the compiled SQL from
  `db.sessions[i].executed`.

## Evals

Retrieval changes need the live evals: `test_retrieval` (Recall@3 ≥ 0.90) and
`test_refusal` (out-of-KB refusal ≥ 0.90), plus `test_end_to_end`. Run
`uv run pytest evals/suites -q` against the stack, and explain any change in the
numbers. If `SHORTLIST_PROVIDER=lexical`, refusal behaviour is **uncalibrated**
(`docs/TODO.md`). Don't read anything into those numbers.

## Done when

- [ ] The ADR-0005 checklist above is ticked, and the PR description says so.
- [ ] Tunables are in Settings.
- [ ] Ordering and failure tests are written and mutation-checked.
- [ ] Evals were run live and the deltas are explained.
