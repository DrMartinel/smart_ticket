"""
LLM inference node — spec §6.2 `infer`. Builds the prompt from retrieved
chunks and few-shots, calls the LLM client, and parses the reply into
`LLMProposalEnvelope`. A parse failure is not an exception: `proposal` stays
None, and core-api sends a run with no proposal to HITL as `schema_invalid`.
"""

from __future__ import annotations

from typing import Any

import json
import logging

from pydantic import ValidationError

from ai_engine.graph.nodes.infer.proposals import LLMProposalEnvelope
from ai_engine.graph.state import TriageState

from ai_engine.graph.build.node import BaseNode
from ai_engine.core.providers import clients
from ai_engine.core.providers.clients import AllLLMDownError
from ai_engine.core.prompts import PROPOSE_PROMPT

logger = logging.getLogger(__name__)

# The shape every reply must take, for the server to decode against. Without
# it the model was free to write any JSON: a `clarify` without its
# `rationale`, or "security" as the `proposed_intent` (evals/HISTORY.md
# 2026-10-04 (4)), each a schema failure sent to a human. The reply is still
# validated below: a server that ignores the schema fails safe.
_PROPOSAL_SCHEMA = LLMProposalEnvelope.model_json_schema()


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
            result = clients.chat.complete(
                PROPOSE_PROMPT,
                user_prompt,
                schema_name="triage_proposal",
                schema=_PROPOSAL_SCHEMA,
            )
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
