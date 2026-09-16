"""
The embedding and reranking seams. Nodes depend on these base classes, never
on a concrete provider module — which is what lets `providers/factory.py` be
the single place that reads
`settings.embedding_provider` / `settings.reranker_provider`.

`LLMClient` follows the same pattern and lives beside its implementation in
`core/llm/base.py`. The database client has a single implementation and no
seam: nodes take `core/db/client.py`'s `SqlAlchemySessionSource` directly.

Nominal (ABC), not structural (Protocol), on purpose: this repo runs no type
checker, so a Protocol was checked by nothing, and a provider with a
misnamed method passed the factory and startup, failing only on the first
ticket that reached it. An `@abstractmethod` makes that a `TypeError` at
construction — `build_providers()` runs at uvicorn import time, so the
process refuses to boot. It checks that the method exists, not its
signature; the contracts below are still enforced by tests.

Every implementation subclasses its seam, test fakes included, so a fake
cannot satisfy a contract production would reject.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """One dense vector of EMBED_DIM floats.

        Raises on provider failure — it must NOT return a zero vector or an
        empty list. Downstream, an empty/degenerate embedding looks exactly
        like "the KB has nothing relevant" (an ordinary refuse-before-LLM)
        rather than "the embedding provider is down" (an infrastructure
        degrade), and those carry different reason codes to HITL.
        """


class Reranker(ABC):
    @abstractmethod
    def score(self, query: str, passages: list[str]) -> list[float]:
        """One score per passage, SAME ORDER as input.

        Named `score`, not `rerank`, because it does not reorder anything:
        ordering and truncation belong to the rerank node. Per ADR-0005 this
        return value is the ONLY number a retrieval threshold is ever
        compared against — never the RRF fusion score, whose magnitude is
        rank-derived and meaningless.
        """
