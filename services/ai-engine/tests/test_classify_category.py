"""
ClassifyCategoryNode tests (ADR-0017). Jev's choice becomes the ticket's
category in core-api's router, so what Jev is shown is the classifier: the
masked ticket and, only when the ticket has one, the title of the page that
answers it. Never chunk text (it pulled tickets to `network` in the probe),
never the cross-encoder's opinion of what is above the floor (ADR-0005).
"""

from __future__ import annotations

from uuid import UUID

import pytest

from ai_engine.core.prompts import CATEGORY_QUESTION
from ai_engine.graph.nodes.classify_category import classifier as classifier_module
from ai_engine.graph.nodes.classify_category.classifier import (
    CategoryChoice,
    JevCategoryClassifier,
)
from ai_engine.graph.nodes.classify_category.node import classify_category
from ai_engine.graph.state import RankedChunk
from ai_engine.schemas import TicketCategory

_ARTICLE = UUID(int=10)


def _chunk(jev: float, cross_encoder: float = 0.5) -> RankedChunk:
    return RankedChunk(
        chunk_id=UUID(int=1),
        article_id=_ARTICLE,
        article_slug="kb-a",
        content="Open the route table and add a route to the NAT gateway.",
        shortlist_score=cross_encoder,
        rerank_score=jev,
    )


@pytest.fixture
def jev(fake_db, fake_classifier, use_db, use_classifier):
    """A fake Jev classifier and the DB the page title comes from."""

    def install(choice=CategoryChoice(TicketCategory.SOFTWARE, 0.9), error=None, titles=None):
        rows = [(_ARTICLE, "Troubleshooting WorkSpaces")] if titles is None else titles
        use_db(fake_db(rows))
        return use_classifier(fake_classifier(choice=choice, error=error))

    return install


# --- failure paths first ------------------------------------------------------


def test_a_jev_failure_propagates(jev, make_state):
    """No fallback to the LLM's category: a silent switch of classifier
    would hide the outage and change what `min_confidence` is calibrated on.
    The run fails, and core-api sends it to a human (`ai_engine_unavailable`)."""

    jev(error=RuntimeError("jev down"))

    with pytest.raises(RuntimeError, match="jev down"):
        classify_category(make_state(reranked=[_chunk(0.9)], retrieval_floor=0.30))


def test_a_choice_that_is_not_a_category_raises(serve, monkeypatch):
    """The question file and `TicketCategory` disagree: a category the
    router can't name is no category, so the run fails to a human."""

    criteria = {**CATEGORY_QUESTION["criteria"], "billing": {"what": "invoices"}}
    question = {**CATEGORY_QUESTION, "criteria": criteria}
    serve("jev", _choice_reply("billing"))

    monkeypatch.setattr(classifier_module, "CATEGORY_QUESTION", question)

    with pytest.raises(ValueError, match="billing"):
        JevCategoryClassifier().classify("s", "b", None)


def test_below_the_floor_jev_is_still_asked_with_no_page(jev, make_state):
    """An out-of-KB ticket gets a category from its own text. A page below
    the floor doesn't answer the ticket, and its title would pull the
    choice towards it."""

    fake = jev()

    out = classify_category(make_state(reranked=[_chunk(0.1)], retrieval_floor=0.30))

    [(_, _, title)] = fake.calls
    assert title is None
    assert out["category_choice"] is TicketCategory.SOFTWARE


def test_no_reranked_chunks_asks_with_no_page(jev, make_state):
    fake = jev()

    classify_category(make_state(reranked=[], retrieval_floor=0.30))

    [(_, _, title)] = fake.calls
    assert title is None


def test_the_page_cutoff_reads_jevs_score_not_the_cross_encoders(jev, make_state):
    """ADR-0005: a chunk the cross-encoder liked (0.9) but Jev didn't (0.1)
    is not a page that answers the ticket."""

    fake = jev()

    classify_category(make_state(reranked=[_chunk(0.1, cross_encoder=0.9)], retrieval_floor=0.30))

    [(_, _, title)] = fake.calls
    assert title is None


# --- behaviour ------------------------------------------------------------------


def test_above_the_floor_only_the_top_pages_title_is_sent(jev, make_state):
    """The title, never the chunk: how to fix a problem names other
    categories' parts (evals/HISTORY.md 2026-10-04 (5))."""

    fake = jev()

    classify_category(make_state(reranked=[_chunk(0.9)], retrieval_floor=0.30))

    [(subject, body, title)] = fake.calls
    assert title == "Troubleshooting WorkSpaces"
    assert "route table" not in f"{subject} {body} {title}"


def test_only_the_masked_ticket_is_sent(jev, make_state):
    fake = jev()
    state = make_state(reranked=[_chunk(0.9)], retrieval_floor=0.30)

    classify_category(state)

    [(subject, body, _)] = fake.calls
    assert (subject, body) == (state.ticket.subject_masked, state.ticket.body_masked)


def test_a_page_with_no_title_row_is_sent_as_no_page(jev, make_state):
    fake = jev(titles=[])

    classify_category(make_state(reranked=[_chunk(0.9)], retrieval_floor=0.30))

    [(_, _, title)] = fake.calls
    assert title is None


def test_the_choice_and_its_confidence_go_on_state(jev, make_state):
    jev(choice=CategoryChoice(TicketCategory.SECURITY, 0.62))

    out = classify_category(make_state(reranked=[_chunk(0.9)], retrieval_floor=0.30))

    assert out == {"category_choice": TicketCategory.SECURITY, "category_confidence": 0.62}


# --- the classifier, through the real Jev client --------------------------------


def _choice_reply(choice: str, confidence: float = 0.8):
    from ai_engine.core.config import settings

    return {
        "model": settings.jev_model,
        "answers": {
            "category": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {choice: confidence},
            }
        },
    }


def test_the_classifier_sends_the_versioned_question_and_the_page_title(serve):
    jev = serve("jev", _choice_reply("network", 0.7))

    out = JevCategoryClassifier().classify("s", "b", "VPN troubleshooting")

    assert out == CategoryChoice(TicketCategory.NETWORK, 0.7)
    [(path, payload)] = jev.sent
    assert path == "/systemone"
    assert payload["questions"] == {"category": CATEGORY_QUESTION}
    assert payload["state"] == {
        "ticket": {"subject": "s", "body": "b"},
        "page": {"title": "VPN troubleshooting"},
    }


def test_the_classifier_sends_no_page_key_without_a_page(serve):
    """The question tells Jev to judge from the ticket alone when there is
    no `page`; an empty page would be a page."""

    jev = serve("jev", _choice_reply("other"))

    JevCategoryClassifier().classify("s", "b", None)

    [(_, payload)] = jev.sent
    assert payload["state"] == {"ticket": {"subject": "s", "body": "b"}}


def test_every_category_is_an_option_and_every_option_a_category():
    """A category with no option can never be chosen; an option with no
    category raises on every ticket Jev puts in it."""

    assert set(CATEGORY_QUESTION["criteria"]) == {c.value for c in TicketCategory}
    assert CATEGORY_QUESTION["type"] == "choice"
