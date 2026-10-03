"""
ai-engine's HTTP surface. core-api is the only caller (spec §1): this
service never calls back into core-api and holds no credentials to write
any business table (ADR-0004).

- `POST /v1/analyze`: the triage graph, on masked text.
- `POST /v1/embed`, `POST /v1/pii/detect`: ai-engine is the only vLLM
  client, so core-api's embeddings and PII NER come through here (ADR-0012).
  `/v1/pii/detect` is the one endpoint that receives RAW text: nothing here
  may log it, echo it or put the model's reply in an error.
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from ai_engine.schemas import (
    AIRunRequest,
    AIRunResponse,
    EmbedRequest,
    EmbedResponse,
    PiiDetectRequest,
    PiiDetectResponse,
)
from ai_engine.graph.state import TriageState

from ai_engine.core.config import settings
from ai_engine.core.providers.embeddings import embedder
from ai_engine.core.providers.pii import pii_detector
from ai_engine.graph.triage import triage_graph

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


app = FastAPI(title="Smart Ticket Triage — ai-engine", version="1.0.0")


@app.exception_handler(RequestValidationError)
async def _validation_error_without_input(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """FastAPI's default 422 echoes the offending `input` back, which for
    `/v1/pii/detect` is raw PII. Keep where and why, drop what."""

    errors = [{k: v for k, v in e.items() if k != "input"} for e in exc.errors()]
    return JSONResponse(status_code=422, content={"detail": jsonable_encoder(errors)})


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
            {
                "chunk_id": r.chunk_id,
                "kb_slug": r.article_slug,
                "rerank_score": r.final_score(),
                "shortlist_score": r.shortlist_score,
            }
            for r in reranked
        ],
        tokens_in=final_state.tokens_in,
        tokens_out=final_state.tokens_out,
        cost_usd=final_state.cost_usd,
        latency_ms=latency_ms,
        degraded_reason=final_state.degraded_reason,
    )


@app.post("/v1/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    """A 502 on any embedder failure, never an empty or zero vector: core-api
    sends the ticket to HITL as `embedding_unavailable`."""

    try:
        vector = embedder.embed(req.text)
    except Exception as e:
        logger.warning("embedder failed: %s", e)
        raise HTTPException(status_code=502, detail=f"embedder failed: {type(e).__name__}") from e
    return EmbedResponse(vector=vector, model=embedder.model)


@app.post("/v1/pii/detect", response_model=PiiDetectResponse)
def detect_pii(req: PiiDetectRequest) -> PiiDetectResponse:
    """A 502 on any NER failure, never []: core-api resolves it to
    `mask_failed`, not "no PII found". Logs and the 502 carry the error
    class only, because the text and the model's reply are both PII."""

    try:
        spans = pii_detector.detect(req.text)
    except Exception as e:
        logger.warning("PII NER failed: %s", type(e).__name__)
        raise HTTPException(status_code=502, detail="PII NER failed") from e
    return PiiDetectResponse(spans=spans)
