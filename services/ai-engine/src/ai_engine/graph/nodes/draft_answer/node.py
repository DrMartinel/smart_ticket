"""
Drafted answer — HyDE (ADR-0021). The draft model (`DRAFT_CLIENT_PROVIDER`,
apart from the proposal's) writes the documentation
passage it expects would answer the ticket, and retrieval searches with it
as well as the ticket: a ticket describes symptoms in the requester's words,
the page that fixes it names features and settings, and the draft is written
in the page's vocabulary.

The draft only chooses what retrieval looks at. It is never shown, quoted,
validated or scored: the cross-encoder and Jev score chunks against the
ticket, and only Jev's score meets a threshold (ADR-0005). A failure raises,
so the ticket goes to a person as `ai_engine_unavailable`; retrieving without
the draft would quietly run the weaker pipeline (rule 3).
"""

from __future__ import annotations

import json
from typing import Any

from ai_engine.core.config import settings
from ai_engine.core.prompts import DRAFT_PROMPT
from ai_engine.core.providers import clients
from ai_engine.core.providers.embeddings import embedder
from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.state import TriageState

_DRAFT_SCHEMA = {
    "type": "object",
    "properties": {"draft": {"type": "string", "minLength": 1}},
    "required": ["draft"],
    "additionalProperties": False,
}


class DraftAnswerNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        ticket = state.ticket
        result = clients.draft.complete(
            DRAFT_PROMPT,
            f"Subject: {ticket.subject_masked}\n\n{ticket.body_masked}",
            schema_name="draft_answer",
            schema=_DRAFT_SCHEMA,
            temperature=settings.draft_temperature,
        )
        reply = json.loads(result.text)
        draft = str(reply.get("draft", "")).strip() if isinstance(reply, dict) else ""
        if not draft:
            raise ValueError("the drafted answer is empty")
        return {"draft_text": draft, "draft_embedding": embedder.embed(draft)}


draft_answer = DraftAnswerNode()
