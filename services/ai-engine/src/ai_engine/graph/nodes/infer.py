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

from pydantic import ValidationError

from contracts.llm_draft import LLMProposalEnvelope

from ai_engine.graph.budget import check_budget
from ai_engine.graph.state import TriageState
from ai_engine.llm.circuit_breaker import CircuitOpenError
from ai_engine.llm.client import AllLLMDownError
from ai_engine.providers.protocols import LLMClient

logger = logging.getLogger(__name__)


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


class InferNode:
    """Read-only after __init__; one instance is shared across FastAPI's
    threadpool."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        system_prompt: str,
        model_timeout_sec: float,
        min_attempt_timeout_sec: float = 5.0,
        attempt_headroom_divisor: int = 2,
    ) -> None:
        self._llm = llm
        # Injected as a STRING, resolved once at startup from
        # settings.prompt_version. Reading the file here (as the old
        # module-level _SYSTEM_PROMPT did) meant importing this module
        # touched the filesystem, and the hardcoded "classify.v3.md" made
        # settings.prompt_version silently inert.
        self._system_prompt = system_prompt
        self._model_timeout_sec = model_timeout_sec
        self._min_attempt_timeout_sec = min_attempt_timeout_sec
        # Not a tunable: this is the arithmetic form of "the fallback chain
        # in llm/client.py gets exactly one more attempt inside the same
        # per-ticket latency budget". If that retry count changes, this
        # changes with it — which is why it is NOT a Settings field that
        # could drift out of sync with the code it describes.
        self._attempt_headroom_divisor = attempt_headroom_divisor

    def __call__(self, state: TriageState) -> dict:
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
        floor = self._min_attempt_timeout_sec
        remaining = max(floor, state["started_at"] + state["max_latency_sec"] - time.time())
        per_attempt_timeout = min(
            self._model_timeout_sec, max(floor, remaining / self._attempt_headroom_divisor)
        )

        try:
            result = self._llm.complete(self._system_prompt, user_prompt, timeout=per_attempt_timeout)
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
