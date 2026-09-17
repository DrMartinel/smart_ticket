"""
The embedding and reranking seams. Nodes depend on these, never on a concrete
provider, so `providers/factory.py` is the single place provider settings are
read. (`LLMClient` lives in `core/llm/base.py`; the DB client has one
implementation and no seam.)

ABCs, not Protocols: nothing type-checks this repo, so a misnamed method must
be a `TypeError` at construction — at boot — not a failure on the first
ticket. Every implementation subclasses its seam, test fakes included.
"""

from __future__ import annotations

from abc import ABC, abstractmethod


class Embedder(ABC):
    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """One dense vector of EMBED_DIM floats.

        Raises on provider failure — never a zero or empty vector.
        That would read as "the KB has nothing relevant" instead of
        "the embedder is down", and the two reach HITL under different
        reason codes.
        """


class Reranker(ABC):
    @abstractmethod
    def score(self, query: str, passages: list[str]) -> list[float]:
        """One score per passage, in input order. Ordering and truncation
        belong to the rerank node.

        Per ADR-0005 this is the ONLY number a retrieval threshold is
        compared against — never the rank-derived RRF score.
        """
