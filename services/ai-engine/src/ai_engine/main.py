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

from ai_engine.core.config import settings
from ai_engine.core.db.client import db
from ai_engine.core.providers.embeddings import embedder
from ai_engine.core.providers.llm import models
from ai_engine.core.providers.reranker import reranker
from ai_engine.core.state import TriageState
from ai_engine.graph.flow import wire_triage
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.infer import InferNode
from ai_engine.graph.nodes.injection import InjectionNode
from ai_engine.graph.nodes.rerank import RerankNode
from ai_engine.graph.nodes.retrieve import HybridRetrieveNode
from ai_engine.graph.nodes.validate import ValidateNode

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Smart Ticket Triage — ai-engine", version="1.0.0")

# Built once, at import time, so a wiring mistake fails the boot rather than a
# request. No constructor below may open a socket or load a model — every
# model is served by vLLM (ADR-0009).
# Tunables are read by the code that uses them, never threaded through here.
_graph = wire_triage(
    injection=InjectionNode(),
    retrieve=HybridRetrieveNode(db=db, embedder=embedder),
    rerank=RerankNode(reranker=reranker),
    fewshots=SelectFewshotsNode(db=db, embedder=embedder),
    infer=InferNode(llm=models.chat),
    validate=ValidateNode(),
    emit=EmitSignalsNode(db=db),
).compile(TriageState)


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
        max_tokens=req.max_tokens,
        max_llm_calls=req.max_llm_calls,
        max_latency_sec=req.max_latency_sec,
        max_graph_iterations=req.max_graph_iterations,
        tokens_used=0,
        llm_calls=0,
        started_at=started_at,
        iteration=0,
    )

    # invoke() returns a plain dict; re-validating gives typed access and the
    # field defaults for anything no node set.
    final_state = TriageState.model_validate(_graph.invoke(initial_state))

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
