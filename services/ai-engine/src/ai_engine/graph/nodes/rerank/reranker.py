"""
The reranker (spec §6.3), RerankNode's scorer: `JevReranker` (ADR-0015),
always on. It scores the shortlist, and its score is the one the floor and
the trust signals read (ADR-0005).

Jev (TypeSafe's hosted System One model) is asked one yes/no question per
chunk, "does this passage fix the ticket's problem?", and answers with a
probability (a Noul). One request per chunk, in parallel: the shape the
probe measured (evals/HISTORY.md 2026-10-02 (4)).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import NamedTuple

from ai_engine.core.prompts import RERANK_QUESTION
from ai_engine.core.providers import clients

# The key the question and its answer travel under. Not sent to the model.
_QUESTION_ID = "resolves"


class Passage(NamedTuple):
    title: str
    text: str


class JevReranker:
    """The reranker (RerankNode). Its own interface, not the shortlister's:
    it scores the ticket's subject and body against titled passages.

    Scores (ticket, passage) pairs with `settings.jev_model` over
    `POST /systemone` through `clients.jev`. No retries, a 429 included: a failed
    call fails the run, and core-api sends the ticket to a human as
    `ai_engine_unavailable`. Stateless.

    Its scores are their own calibration, which `retrieval.floor` is set on
    (ADR-0005, ADR-0015). Only masked ticket text is sent; the passages are
    KB text.
    """

    def score(self, subject: str, body: str, passages: list[Passage]) -> list[float]:
        """One score in [0, 1] per passage, in input order. Raises on any
        failure, including a single passage that could not be scored: never
        a partial list."""

        if not passages:
            return []
        ticket = {"subject": subject, "body": body}
        with ThreadPoolExecutor(max_workers=len(passages)) as pool:
            # `map` re-raises the first failure when its result is read, so
            # one failed passage fails the whole list.
            return list(pool.map(lambda p: self._score_one(ticket, p), passages))

    def _score_one(self, ticket: dict[str, str], passage: Passage) -> float:
        state = {"ticket": ticket, "passage": {"title": passage.title, "text": passage.text}}
        return clients.jev.ask(state, {_QUESTION_ID: RERANK_QUESTION})[_QUESTION_ID]


# --- The reranker, built once when this module is imported (no I/O) ----------
# Tests swap in a fake, so they need no key.

reranker = JevReranker()
