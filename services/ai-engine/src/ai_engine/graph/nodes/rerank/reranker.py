"""
The reranker (spec §6.3), RerankNode's scorer: `JevReranker` (ADR-0026),
always on. It ranks the shortlist, and its score is the one the floor and
the trust signals read (ADR-0005).

Jev (TypeSafe's hosted System One model) is asked one choice question per
ticket over the whole shortlist: which passage fixes the ticket's problem,
or none. Each passage's score is the probability Jev gives its option.
"""

from __future__ import annotations

from typing import Any, NamedTuple

from ai_engine.core.prompts import RERANK_QUESTION
from ai_engine.core.providers import clients

# The key the question and its answer travel under. Not sent to the model.
_QUESTION_ID = "resolves"
# The option that no passage fixes the problem.
_NONE = "none"
# Each passage's option description.
_PASSAGE_OPTION: str = RERANK_QUESTION["passage_option"]
if set(RERANK_QUESTION["criteria"]) != {_NONE}:
    raise ValueError(f"the rerank question's only criterion must be {_NONE!r}")


class Passage(NamedTuple):
    title: str
    text: str


class RerankChoice(NamedTuple):
    """Jev's answer over the passages: one probability per passage in input
    order, the passage chosen (`None` when Jev chose none) and how sure."""

    scores: list[float]
    choice: int | None
    confidence: float


class JevReranker:
    """The reranker (RerankNode). Its own interface, not the shortlister's:
    it ranks titled passages against the ticket's subject and body.

    One `POST /systemone` per ticket with `settings.jev_model` through
    `clients.jev`. No retries, a 429 included: a failed call fails the run,
    and core-api sends the ticket to a human as `ai_engine_unavailable`.
    Stateless. Only masked ticket text is sent; the passages are KB text.
    """

    def rank(self, subject: str, body: str, passages: list[Passage]) -> RerankChoice:
        """Raises on any failure, including a reply that leaves out a
        passage: never a partial list."""

        keys = [f"c{i}" for i in range(1, len(passages) + 1)]
        state = {
            "ticket": {"subject": subject, "body": body},
            "passages": {k: {"title": p.title, "text": p.text} for k, p in zip(keys, passages)},
        }
        answer = clients.jev.choose(state, _QUESTION_ID, self._question(keys, passages))
        return RerankChoice(
            scores=[answer.probabilities[k] for k in keys],
            choice=None if answer.choice == _NONE else keys.index(answer.choice),
            confidence=answer.confidence,
        )

    @staticmethod
    def _question(keys: list[str], passages: list[Passage]) -> dict[str, Any]:
        options = {k: _PASSAGE_OPTION.format(key=k, title=p.title) for k, p in zip(keys, passages)}
        return {
            "type": RERANK_QUESTION["type"],
            "instructions": RERANK_QUESTION["instructions"],
            "criteria": {**options, **RERANK_QUESTION["criteria"]},
        }


# --- The reranker, built once when this module is imported (no I/O) ----------
# Tests swap in a fake, so they need no key.

reranker = JevReranker()
