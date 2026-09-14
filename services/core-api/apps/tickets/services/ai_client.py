"""
HTTP client for ai-engine's `POST /v1/analyze`. core-api is the only
caller; ai-engine never calls back into core-api (spec §1: ai-engine has
no DB credentials to write business tables and no routing authority).
"""

from __future__ import annotations

import httpx
from django.conf import settings

from contracts.ai_request import AIRunRequest, AIRunResponse
from contracts.ticket import TicketMasked


class AIEngineUnavailable(Exception):
    """Raised on any transport failure. Callers MUST treat this as
    fail-open-to-human (spec §10.3: "ai-engine down → tất cả vào HITL"),
    never as "skip the AI step and auto-approve"."""


def analyze(ticket: TicketMasked, request_id: str) -> AIRunResponse:
    th = settings.THRESHOLDS
    req = AIRunRequest(
        request_id=request_id,
        ticket=ticket,
        retrieval_floor=th.retrieval_floor,
        max_tokens=th.budget.max_tokens_per_ticket,
        max_llm_calls=th.budget.max_llm_calls,
        max_latency_sec=th.budget.max_latency_sec,
        max_graph_iterations=th.budget.max_graph_iterations,
    )
    url = f"{settings.AI_ENGINE_URL.rstrip('/')}/v1/analyze"
    try:
        resp = httpx.post(
            url, json=req.model_dump(mode="json"), timeout=th.budget.max_latency_sec + 5
        )
        resp.raise_for_status()
        return AIRunResponse(**resp.json())
    except (httpx.HTTPError, ValueError) as e:
        raise AIEngineUnavailable(str(e)) from e
