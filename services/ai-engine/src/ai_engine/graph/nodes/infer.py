"""
LLM inference node — spec §6.2 node `infer`. Builds the prompt from
retrieved chunks + few-shots, calls llm/client.py (which owns circuit
breaker / retry / fallback), and attempts to parse the result into
`LLMProposalEnvelope`. Parse/validation failure here is NOT an exception
— it's recorded as `schema_valid=False` in validate.py and the graph's
own retry edge (`validate -> infer`, capped at iteration < 2) gives the
model exactly one more chance before the router sends it to HITL.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from pydantic import ValidationError

from contracts.llm_draft import LLMProposalEnvelope

from ai_engine.graph.budget import check_budget
from ai_engine.graph.state import TriageState
from ai_engine.config import settings
from ai_engine.llm.circuit_breaker import CircuitOpenError
from ai_engine.llm.client import AllLLMDownError, chat_complete

logger = logging.getLogger(__name__)

_PROMPT_PATH = Path(__file__).resolve().parents[2] / "llm" / "prompts" / "classify.v3.md"
_SYSTEM_PROMPT = _PROMPT_PATH.read_text()


def _format_chunks(reranked: list) -> str:
    if not reranked:
        return "(no relevant excerpts found)"
    # kb_slug is what the model must echo back in AutoReplyProposal.kb_slug
    # — showing only chunk_id/article_id here previously left the model to
    # invent something for kb_slug, since it was never actually told it.
    return "\n\n".join(
        f"[kb_slug={c.article_slug}, chunk_id={c.chunk_id}]\n{c.content}" for c in reranked
    )


def _format_fewshots(fewshots: list[dict]) -> str:
    if not fewshots:
        return "(none available)"
    return "\n\n".join(
        f"Input: {f['input_text']}\nOutput: {json.dumps(f['output_json'], ensure_ascii=False)}" for f in fewshots
    )


def llm_infer(state: TriageState) -> dict:
    degraded = check_budget(state)
    if degraded:
        return {"proposal": None, "degraded_reason": degraded}

    ticket = state["ticket"]
    reranked = state.get("reranked", [])
    fewshots = state.get("fewshots", [])

    user_prompt = (
        f"## KB excerpts\n{_format_chunks(reranked)}\n\n"
        f"## Few-shot examples\n{_format_fewshots(fewshots)}\n\n"
        f"## Ticket\nSubject: {ticket.subject_masked}\nBody: {ticket.body_masked}"
    )

    # Leave headroom for the fallback attempt within the same per-ticket
    # latency budget rather than using the full budget on a single try,
    # then clamp to the per-call model ceiling — whichever binds first
    # wins. The budget protects the ticket's end-to-end latency; the
    # ceiling protects against a single call hanging indefinitely.
    remaining = max(5.0, state["started_at"] + state["max_latency_sec"] - time.time())
    per_attempt_timeout = min(settings.model_timeout_sec, max(5.0, remaining / 2))

    try:
        result = chat_complete(_SYSTEM_PROMPT, user_prompt, timeout=per_attempt_timeout)
    except CircuitOpenError:
        return {"proposal": None, "degraded_reason": "circuit_open"}
    except AllLLMDownError:
        return {"proposal": None, "degraded_reason": "all_llm_down"}

    update = {
        "tokens_used": state["tokens_used"] + result.tokens_in + result.tokens_out,
        "llm_calls": state["llm_calls"] + 1,
        "tokens_in": state.get("tokens_in", 0) + result.tokens_in,
        "tokens_out": state.get("tokens_out", 0) + result.tokens_out,
        "cost_usd": state.get("cost_usd", 0.0) + result.cost_usd,
        "model_used": result.model,
    }
    if result.degraded_reason:
        update["degraded_reason"] = result.degraded_reason

    try:
        parsed = json.loads(result.text)
        proposal = LLMProposalEnvelope(root=parsed)
        update["proposal"] = proposal
    except (json.JSONDecodeError, ValidationError, TypeError) as e:
        logger.warning("infer: LLM output failed schema validation: %s", e)
        update["proposal"] = None

    return update
