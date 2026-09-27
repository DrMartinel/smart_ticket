"""
LLM inference node — spec §6.2 `infer`. Builds the prompt from retrieved
chunks and few-shots, calls the LLM client, and parses the reply into
`LLMProposalEnvelope`. A parse failure is not an exception: validate records
`schema_valid=False` and the ticket goes to HITL.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import ValidationError

from contracts.llm_draft import LLMProposalEnvelope

from ai_engine.core.config import settings
from ai_engine.core.node import BaseNode, StateUpdate
from ai_engine.core.providers.llm import models
from ai_engine.core.providers.llm.models import AllLLMDownError
from ai_engine.core.prompts import load_system_prompt
from ai_engine.core.state import RankedChunk, TriageState

logger = logging.getLogger(__name__)


def _format_chunks(reranked: list[RankedChunk]) -> str:
    if not reranked:
        return "(no relevant excerpts found)"
    # kb_slug is what the model must echo back in AutoReplyProposal.kb_slug
    # — showing only chunk_id/article_id here previously left the model to
    # invent something for kb_slug, since it was never actually told it.
    return "\n\n".join(
        f"[kb_slug={c.article_slug}, chunk_id={c.chunk_id}]\n{c.content}" for c in reranked
    )


def _format_fewshots(fewshots: list[dict[str, Any]]) -> str:
    if not fewshots:
        return "(none available)"
    return "\n\n".join(
        f"Input: {f['input_text']}\nOutput: {json.dumps(f['output_json'], ensure_ascii=False)}"
        for f in fewshots
    )


class InferNode(BaseNode):
    def __init__(self) -> None:
        # Loaded at construction, so a missing prompt file fails the boot.
        self._system_prompt = load_system_prompt(settings.prompt_version)

    def __call__(self, state: TriageState) -> StateUpdate:
        ticket = state.ticket
        reranked = state.reranked
        fewshots = state.fewshots

        user_prompt = (
            f"## KB excerpts\n{_format_chunks(reranked)}\n\n"
            f"## Few-shot examples\n{_format_fewshots(fewshots)}\n\n"
            f"## Ticket\nSubject: {ticket.subject_masked}\nBody: {ticket.body_masked}"
        )

        try:
            result = models.chat.complete(self._system_prompt, user_prompt)
        except AllLLMDownError:
            return {"proposal": None, "degraded_reason": "all_llm_down"}

        update: StateUpdate = {
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
