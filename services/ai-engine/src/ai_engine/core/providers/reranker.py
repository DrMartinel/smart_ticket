"""
The reranker nodes depend on (spec §6.3). It owns the contract, not the model:
the injected `LLMClient` scores the pairs, and this class checks the scores can
be zipped back onto the passages.

Clients' scores are separate calibrations: `retrieval.floor` is a
cross-encoder number (ADR-0005), so under `LexicalClient` it is silently
compared against token-overlap ratios.
"""

from __future__ import annotations

from ai_engine.core.providers.llm.client import LLMClient


class Reranker:
    """Scores query/passage pairs through any `LLMClient` that serves
    reranking.

    Raises at construction if the client does not, so a misconfigured
    provider fails the boot rather than the first ticket. There is no
    fallback between clients: they are different calibrations (ADR-0005).
    Read-only after construction.
    """

    def __init__(self, *, client: LLMClient) -> None:
        if not client.supports("rerank"):
            raise TypeError(f"{type(client).__name__} does not serve reranking")
        self._client = client

    def score(self, query: str, passages: list[str]) -> list[float]:
        """One score per passage, in input order. Ordering and truncation
        belong to the rerank node.

        Per ADR-0005 this is the ONLY number a retrieval threshold is
        compared against — never the rank-derived RRF score.
        """

        if not passages:
            return []
        scores = self._client.rerank(query, passages)
        # The rerank node zips scores against its candidates POSITIONALLY, so
        # a short or padded list would attach relevance to the wrong chunk
        # while the ranking still looks plausible.
        if len(scores) != len(passages):
            raise ValueError(
                f"{self._client.model_name!r} returned {len(scores)} scores "
                f"for {len(passages)} passages"
            )
        return scores
