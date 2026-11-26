"""
The category classifier (ADR-0017), ClassifyCategoryNode's provider: Jev
answers one choice question per ticket, which of the categories core-api
sent it is (ADR-0049). Its choice is the ticket's category; the LLM proposes
none (propose.v8).

The state is the masked ticket and, when the ticket has one, the title of
the KB page that answers it. Never the page's text: how to fix a problem
names other categories' parts (route tables in a WorkSpaces fix), and with
the text Jev's choice followed them (evals/HISTORY.md 2026-10-04 (5)).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, NamedTuple

from ai_engine.core.prompts import CATEGORY_QUESTION
from ai_engine.core.providers import clients
from ai_engine.graph.ticket import CategoryOption

# The key the question and its answer travel under. Not sent to the model.
_QUESTION_ID = "category"


class CategoryChoice(NamedTuple):
    category: str
    confidence: float


def category_question(categories: Sequence[CategoryOption]) -> dict[str, Any]:
    """The versioned question's instructions, with one option per category."""
    return {
        "type": CATEGORY_QUESTION["type"],
        "instructions": CATEGORY_QUESTION["instructions"],
        "criteria": {c.slug: {"what": c.description} for c in categories},
    }


class JevCategoryClassifier:
    """One `POST /systemone` per ticket through `clients.jev`, no retries: a
    failed call fails the run, and core-api sends the ticket to a human as
    `ai_engine_unavailable`. Stateless."""

    def classify(
        self,
        *,
        subject: str,
        body: str,
        page_title: str | None,
        categories: Sequence[CategoryOption],
    ) -> CategoryChoice:
        """Raises on any failure, and on a choice that is not one of `categories`."""

        state: dict[str, Any] = {"ticket": {"subject": subject, "body": body}}
        if page_title is not None:
            state["page"] = {"title": page_title}
        answer = clients.jev.choose(state, _QUESTION_ID, category_question(categories))
        return CategoryChoice(answer.choice, answer.confidence)


# --- The classifier, built once when this module is imported (no I/O) --------
# Tests swap in a fake, so they need no key.

classifier = JevCategoryClassifier()
