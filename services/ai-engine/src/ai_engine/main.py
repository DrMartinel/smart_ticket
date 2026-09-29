"""
ai-engine's only HTTP surface: `POST /v1/analyze`. core-api is the only
caller (spec §1) — this service never calls back into core-api and holds
no credentials to write any business table (ADR-0004).
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI

from ai_engine.core.state import AIRunRequest, AIRunResponse, TriageState

from ai_engine.core.config import settings
from ai_engine.graph.triage import triage_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Smart Ticket Triage — ai-engine", version="1.0.0")


@app.get("/healthz")
def healthz():
    return {"status": "ok", "graph_version": settings.graph_version}


@app.post("/v1/analyze", response_model=AIRunResponse)
def analyze(req: AIRunRequest) -> AIRunResponse:
    started_at = time.time()

    initial_state = TriageState(
        ticket=req.ticket,
        request_id=req.request_id,
        retrieval_floor=req.retrieval_floor,
    )

    # invoke() returns a plain dict; re-validating gives typed access and the
    # field defaults for anything no node set.
    final_state = TriageState.model_validate(triage_graph.invoke(initial_state))

    # EmitSignalsNode is on every path (graph/build.py), so this means miswiring.
    # Raising gives core-api a 500, which it sends to a human.
    if final_state.signals is None:
        raise RuntimeError("triage graph finished without emitting signals")

    latency_ms = int((time.time() - started_at) * 1000)
    reranked = final_state.reranked

    return AIRunResponse(
        request_id=req.request_id,
        graph_version=settings.graph_version,
        prompt_version=req.prompt_version,
        model=final_state.model_used or "n/a",
        proposal=final_state.proposal,
        signals=final_state.signals,
        retrieved_chunks=[
            {"chunk_id": r.chunk_id, "kb_slug": r.article_slug, "rerank_score": r.score}
            for r in reranked
        ],
        tokens_in=final_state.tokens_in,
        tokens_out=final_state.tokens_out,
        cost_usd=final_state.cost_usd,
        latency_ms=latency_ms,
        degraded_reason=final_state.degraded_reason,
    )
