"""
The option scorer (ADR-0023, ADR-0026), ScoreOptionsNode's provider:
`JevOptionScorer` asks Jev one yes/no question per page a clarifying
question may offer, "does this passage fix the ticket's problem?", each
page judged on its own. core-api picks the buttons from these scores.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from ai_engine.core.prompts import OPTION_QUESTION
from ai_engine.core.providers import clients
from ai_engine.graph.nodes.rerank.reranker import Passage

# The key the question and its answer travel under. Not sent to the model.
_QUESTION_ID = "resolves"


class JevOptionScorer:
    """One `POST /systemone` per passage, in parallel, through `clients.jev`.
    No retries: a failed call fails the run, and core-api sends the ticket
    to a human as `ai_engine_unavailable`. Stateless. Only masked ticket
    text is sent; the passages are KB text."""

    def score(self, subject: str, body: str, passages: list[Passage]) -> list[float]:
        """One probability per passage, in input order. Raises on any
        failure, including a single passage: never a partial list."""

        if not passages:
            return []
        ticket = {"subject": subject, "body": body}
        with ThreadPoolExecutor(max_workers=len(passages)) as pool:
            return list(pool.map(lambda p: self._score_one(ticket, p), passages))

    @staticmethod
    def _score_one(ticket: dict[str, str], passage: Passage) -> float:
        state = {"ticket": ticket, "passage": {"title": passage.title, "text": passage.text}}
        return clients.jev.ask(state, _QUESTION_ID, OPTION_QUESTION)


# --- The scorer, built once when this module is imported (no I/O) ------------
# Tests swap in a fake, so they need no key.

option_scorer = JevOptionScorer()
