"""
ClassifyCategoryNode tests (ADR-0017). Jev's choice becomes the ticket's
category in core-api's router, so what Jev is shown is the classifier: the
masked ticket and, only when the ticket has one, the title of the page that
answers it. Never chunk text (it pulled tickets to `network` in the probe),
never the cross-encoder's opinion of what is above the floor (ADR-0005).
"""

from __future__ import annotations

import json
from uuid import UUID

import pytest

from ai_engine.core.prompts import CATEGORY_QUESTION, load_question
from ai_engine.graph.nodes.classify_category.classifier import (
    CategoryChoice,
    JevCategoryClassifier,
    category_question,
)
from ai_engine.graph.nodes.classify_category.node import ClassifyCategoryOutcome, classify_category
from ai_engine.graph.state import RankedChunk
from ai_engine.graph.ticket import CategoryOption

_ARTICLE = UUID(int=10)
_V2 = load_question("category.v2")
_SEED = [CategoryOption(slug=s, description=o["what"]) for s, o in _V2["criteria"].items()]


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

    def install(choice=CategoryChoice("software", 0.9), error=None, titles=None):
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


def test_a_choice_that_is_not_a_sent_category_raises(serve):
    """A category core-api didn't send is no category the router can name,
    so the run fails to a human."""

    serve("jev", _choice_reply("billing", options=["billing", *(c.slug for c in _SEED)]))

    with pytest.raises(ValueError, match="billing"):
        JevCategoryClassifier().classify("s", "b", None, _SEED)


def test_below_the_floor_jev_is_still_asked_with_no_page(jev, make_state):
    """An out-of-KB ticket gets a category from its own text. A page below
    the floor doesn't answer the ticket, and its title would pull the
    choice towards it."""

    fake = jev()

    out = classify_category(make_state(reranked=[_chunk(0.1)], retrieval_floor=0.30))

    [(_, _, title)] = fake.calls
    assert title is None
    assert out["category_choice"] == "software"


def test_jev_choosing_no_passage_is_below_the_floor(jev, make_state):
    """Checks that a `none` rerank choice skips the LLM and sends no page,
    whatever the top chunk's score."""

    fake = jev()
    state = make_state(reranked=[_chunk(0.9)], retrieval_floor=0.30, rerank_choice=None)

    classify_category(state)

    [(_, _, title)] = fake.calls
    assert title is None
    assert classify_category.decide(state) is ClassifyCategoryOutcome.EVIDENCE_BELOW_FLOOR


def test_a_split_choice_with_a_high_total_reaches_the_llm(jev, make_state):
    """Checks that the floor reads Jev's passages' total, not its top-1: an
    ambiguous ticket spreads probability between readings (ADR-0026)."""

    jev()
    state = make_state(reranked=[_chunk(0.25)], rerank_total=0.8, retrieval_floor=0.6)

    assert classify_category.decide(state) is ClassifyCategoryOutcome.EVIDENCE_ABOVE_FLOOR


def test_a_total_below_the_floor_is_refused_even_with_a_choice(jev, make_state):
    jev()
    state = make_state(reranked=[_chunk(0.5)], rerank_total=0.55, retrieval_floor=0.6)

    assert classify_category.decide(state) is ClassifyCategoryOutcome.EVIDENCE_BELOW_FLOOR


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
    jev(choice=CategoryChoice("security", 0.62))

    out = classify_category(make_state(reranked=[_chunk(0.9)], retrieval_floor=0.30))

    assert out == {"category_choice": "security", "category_confidence": 0.62}


# --- the classifier, through the real Jev client --------------------------------


def _choice_reply(choice: str, confidence: float = 0.8, options: list[str] | None = None):
    from ai_engine.core.config import settings

    options = options if options is not None else [c.slug for c in _SEED]

    return {
        "model": settings.jev_model,
        "answers": {
            "category": {
                "type": "choice",
                "choice": choice,
                "confidence": confidence,
                "probabilities": {c: confidence if c == choice else 0.0 for c in options},
            }
        },
    }


def test_the_classifier_sends_the_versioned_question_and_the_page_title(serve):
    jev = serve("jev", _choice_reply("network", 0.7))

    out = JevCategoryClassifier().classify("s", "b", "VPN troubleshooting", _SEED)

    assert out == CategoryChoice("network", 0.7)
    [(path, payload)] = jev.sent
    assert path == "/systemone"
    assert payload["questions"] == {"category": category_question(_SEED)}
    assert payload["state"] == {
        "ticket": {"subject": "s", "body": "b"},
        "page": {"title": "VPN troubleshooting"},
    }


def test_the_classifier_sends_no_page_key_without_a_page(serve):
    """The question tells Jev to judge from the ticket alone when there is
    no `page`; an empty page would be a page."""

    jev = serve("jev", _choice_reply("other"))

    JevCategoryClassifier().classify("s", "b", None, _SEED)

    [(_, payload)] = jev.sent
    assert payload["state"] == {"ticket": {"subject": "s", "body": "b"}}


def test_the_question_offers_exactly_the_sent_categories(serve):
    """A seventh row is offered once core-api sends it; a category it
    stopped sending is never offered (ADR-0049)."""

    sent = [
        CategoryOption(slug="network", description="Connectivity."),
        CategoryOption(slug="billing", description="Invoices and refunds."),
    ]
    jev = serve("jev", _choice_reply("billing", options=["network", "billing"]))

    out = JevCategoryClassifier().classify("s", "b", None, sent)

    assert out == CategoryChoice("billing", 0.8)
    [(_, payload)] = jev.sent
    question = payload["questions"]["category"]
    assert question["criteria"] == {
        "network": {"what": "Connectivity."},
        "billing": {"what": "Invoices and refunds."},
    }
    assert question["instructions"] == CATEGORY_QUESTION["instructions"]


def test_the_seeded_categories_ask_what_category_v2_asked():
    """The six seeded rows carry category.v2's descriptions, so in v2's
    order the question Jev reads is v2's, byte for byte."""

    assert json.dumps(category_question(_SEED)) == json.dumps(_V2)


def test_the_versioned_question_holds_no_categories_of_its_own():
    """Options in the file would be a second category set to keep in step."""

    assert "criteria" not in CATEGORY_QUESTION
    assert CATEGORY_QUESTION["type"] == "choice"


def test_the_node_offers_the_requests_categories(jev, make_state):
    fake = jev()
    sent = [CategoryOption(slug="network", description="Connectivity.")]

    classify_category(make_state(reranked=[_chunk(0.9)], retrieval_floor=0.30, categories=sent))

    assert fake.offered == [sent]
