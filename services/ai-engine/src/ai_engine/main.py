"""
ai-engine's only HTTP surface: `POST /v1/analyze`. core-api is the only
caller (spec §1) — this service never calls back into core-api and holds
no credentials to write any business table (ADR-0004).
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI

from contracts.ai_request import AIRunRequest, AIRunResponse

from ai_engine.config import settings
from ai_engine.graph.build import build_graph
from ai_engine.graph.state import TriageState

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Smart Ticket Triage — ai-engine", version="1.0.0")

_graph = build_graph()


@app.get("/healthz")
def healthz():
    return {"status": "ok", "graph_version": settings.graph_version}


@app.post("/v1/analyze", response_model=AIRunResponse)
def analyze(req: AIRunRequest) -> AIRunResponse:
    started_at = time.time()

    initial_state: TriageState = {
        "ticket": req.ticket,
        "request_id": req.request_id,
        "retrieval_floor": req.retrieval_floor,
        "max_tokens": req.max_tokens,
        "max_llm_calls": req.max_llm_calls,
        "max_latency_sec": req.max_latency_sec,
        "max_graph_iterations": req.max_graph_iterations,
        "tokens_used": 0,
        "llm_calls": 0,
        "started_at": started_at,
        "iteration": 0,
    }

    final_state = _graph.invoke(initial_state)

    latency_ms = int((time.time() - started_at) * 1000)
    reranked = final_state.get("reranked") or []

    return AIRunResponse(
        request_id=req.request_id,
        graph_version=settings.graph_version,
        prompt_version=req.prompt_version,
        model=final_state.get("model_used", "n/a"),
        proposal=final_state.get("proposal"),
        signals=final_state["signals"],
        retrieved_chunks=[
            {"chunk_id": r.chunk_id, "kb_slug": r.article_slug, "rerank_score": r.score} for r in reranked
        ],
        tokens_in=final_state.get("tokens_in", 0),
        tokens_out=final_state.get("tokens_out", 0),
        cost_usd=final_state.get("cost_usd", 0.0),
        latency_ms=latency_ms,
        degraded_reason=final_state.get("degraded_reason"),
    )
