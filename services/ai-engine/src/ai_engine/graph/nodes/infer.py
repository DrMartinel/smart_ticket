"""
LLM inference node — spec §6.2 `infer`. Builds the prompt from retrieved
chunks and few-shots, calls the LLM client, and parses the reply into
`LLMProposalEnvelope`. A parse failure is not an exception: validate records
`schema_valid=False` and the ticket goes to HITL.
"""

from __future__ import annotations

from typing import Any

import json
import logging

from pydantic import ValidationError

from ai_engine.schemas import LLMProposalEnvelope
from ai_engine.graph.state import TriageState

from ai_engine.graph.build.node import BaseNode
from ai_engine.core.providers import clients
from ai_engine.core.providers.clients import AllLLMDownError
from ai_engine.core.prompts import CLASSIFY_PROMPT

logger = logging.getLogger(__name__)


class InferNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        ticket = state.ticket
        excerpts = "\n\n".join(
            f"[kb_slug={c.article_slug}, chunk_id={c.chunk_id}]\n{c.content}"
            for c in state.reranked
        )
        examples = "\n\n".join(
            f"Input: {f['input_text']}\nOutput: {json.dumps(f['output_json'], ensure_ascii=False)}"
            for f in state.fewshots
        )

        user_prompt = (
            f"## KB excerpts\n{excerpts or '(no relevant excerpts found)'}\n\n"
            f"## Few-shot examples\n{examples or '(none available)'}\n\n"
            f"## Ticket\nSubject: {ticket.subject_masked}\nBody: {ticket.body_masked}"
        )

        try:
            result = clients.chat.complete(CLASSIFY_PROMPT, user_prompt)
        except AllLLMDownError:
            return {"proposal": None, "degraded_reason": "all_llm_down"}

        update: dict[str, Any] = {
            "tokens_in": result.tokens_in,
            "tokens_out": result.tokens_out,
            "cost_usd": result.cost_usd,
            "model_used": result.model,
        }

        try:
            parsed = json.loads(result.text)
            proposal = LLMProposalEnvelope(root=parsed)
            update["proposal"] = proposal
        except (json.JSONDecodeError, ValidationError, TypeError) as e:
            logger.warning("infer: LLM output failed schema validation: %s", e)
            update["proposal"] = None

        return update


infer = InferNode()
