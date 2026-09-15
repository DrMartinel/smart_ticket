"""
The four seams between a graph node and the outside world. Nodes depend on
these base classes, never on a concrete provider module — which is what makes
every node constructible in a test with no DB, no Ollama and no model
download, and what lets `providers/factory.py` be the single place that
reads `settings.embedding_provider` / `settings.reranker_provider`.

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
from contextlib import AbstractContextManager
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # keeps `core` free of a runtime import of `llm`
    from ai_engine.llm.client import LLMResult


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


class LLMClient(ABC):
    @abstractmethod
    def complete(
        self, system_prompt: str, user_prompt: str, *, timeout: float | None = None
    ) -> LLMResult:
        """Implementations own circuit breaking / retry / fallback (spec
        §10.3) and signal exhaustion by RAISING CircuitOpenError or
        AllLLMDownError — never by returning empty text, which the infer
        node would parse as a schema failure and attribute to the model,
        sending the ticket to HITL under the wrong reason code.
        """


class ConnectionSource(ABC):
    @abstractmethod
    def connect(self) -> AbstractContextManager[Any]:
        """A context manager yielding something with `.cursor()`.

        Typed `Any` rather than `psycopg.Connection` deliberately: the
        retrieval layer (`bm25_search`, `vector_search`) already takes an
        untyped `conn`, and a stricter annotation would make every test
        fake a lie.
        """
