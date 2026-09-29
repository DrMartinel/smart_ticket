"""
core-api's client for ai-engine; the wire schema it speaks is in
`infrastructure/dtos.py`. core-api is the only caller; ai-engine never calls
back into core-api (spec §1: ai-engine has no DB credentials to write
business tables and no routing authority).

ai-engine is also the only vLLM client (ADR-0012), so every model call
core-api makes goes through `AIEngineClient`: triage (`analyze`),
embeddings (`embed`) and Tier-2 PII NER (`detect_pii`). This module is
transport only. What a failure means is decided by the caller, and it is
always toward a human.
"""

from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings
from pydantic import BaseModel

from infrastructure.dtos import (
    EMBED_DIM,
    AIRunRequest,
    AIRunResponse,
    EmbedRequest,
    EmbedResponse,
    PiiDetectRequest,
    PiiDetectResponse,
    TicketMasked,
)


class AIEngineUnavailable(Exception):
    """Raised by `analyze` on any transport failure. Callers MUST treat this
    as fail-open-to-human (spec §10.3: "ai-engine down → tất cả vào HITL"),
    never as "skip the AI step and auto-approve"."""


class AIEngineClient:
    """Every call to ai-engine. Builds the URL from `AI_ENGINE_URL` and the
    request from the wire schema; no caller does either by hand.

    Settings are read on each call, not at construction, so tests and
    `override_settings` apply without rebuilding the client. Construction
    opens no socket.

    Connect and read are budgeted separately on purpose — see
    MODEL_CONNECT_TIMEOUT_SEC in settings. An unreachable ai-engine is
    knowable in seconds; only a reachable but busy one (a cold model load)
    deserves the full read budget.
    """

    def analyze(self, ticket: TicketMasked, request_id: str) -> AIRunResponse:
        """Raises `AIEngineUnavailable` on any failure."""
        th = settings.THRESHOLDS
        req = AIRunRequest(
            request_id=request_id,
            ticket=ticket,
            retrieval_floor=th.retrieval_floor,
        )
        # Read: the whole run's latency budget, plus a little slack so a run
        # that finishes right at the budget still delivers its response.
        read = th.budget.max_latency_sec + settings.AI_ENGINE_ANALYZE_GRACE_SEC
        try:
            return AIRunResponse(**self._post("/v1/analyze", req, read_timeout=read))
        except (httpx.HTTPError, ValueError) as e:
            raise AIEngineUnavailable(str(e)) from e

    def embed(self, text: str) -> EmbedResponse:
        """The vector and the model that produced it, for tickets, KB chunks
        and few-shot examples alike, so every vector in the system comes
        from ai-engine's one embedder (ADR-0012).

        Raises `httpx.HTTPError` or `ValueError` on any failure — the two
        types `process_ticket` turns into an `embedding_unavailable` HITL
        route. Anything else would escape the Celery task and leave the
        ticket stuck at status="new", invisible to every queue. ai-engine
        answers 502 rather than an empty vector."""
        body = self._post(
            "/v1/embed", EmbedRequest(text=text), read_timeout=settings.MODEL_TIMEOUT_SEC
        )
        embedding = EmbedResponse.model_validate(body)
        # A wrong width would otherwise fail far away, as a database error.
        if len(embedding.vector) != EMBED_DIM:
            raise ValueError(
                f"embedding model {embedding.model!r} returned {len(embedding.vector)}, "
                f"expected {EMBED_DIM} dims — check ai-engine's EMBED_MODEL"
            )
        return embedding

    async def detect_pii(self, text: str) -> list[str]:
        """Raises `httpx.HTTPError` or `ValueError` on any failure. Callers
        MUST treat that as MASK_FAILED, never as "no PII found". Async so
        masking can run subject and body concurrently."""
        body = await self._apost(
            "/v1/pii/detect", PiiDetectRequest(text=text), read_timeout=settings.MODEL_TIMEOUT_SEC
        )
        return PiiDetectResponse.model_validate(body).spans

    def _post(self, path: str, body: BaseModel, *, read_timeout: float) -> Any:
        with httpx.Client(
            base_url=settings.AI_ENGINE_URL, timeout=self._timeout(read_timeout)
        ) as client:
            resp = client.post(path, json=body.model_dump(mode="json"))
            resp.raise_for_status()
            return resp.json()

    async def _apost(self, path: str, body: BaseModel, *, read_timeout: float) -> Any:
        async with httpx.AsyncClient(
            base_url=settings.AI_ENGINE_URL, timeout=self._timeout(read_timeout)
        ) as client:
            resp = await client.post(path, json=body.model_dump(mode="json"))
            resp.raise_for_status()
            return resp.json()

    @staticmethod
    def _timeout(read: float) -> httpx.Timeout:
        return httpx.Timeout(float(read), connect=float(settings.MODEL_CONNECT_TIMEOUT_SEC))


# --- The client, built once at import. Opens no socket. ----------------------

ai_engine = AIEngineClient()
