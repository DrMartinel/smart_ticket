"""
Rerank output type — spec §6.3. Lives in `core` so `TriageState` can type
`reranked` without importing from `graph`.

`score` is the cross-encoder score, the only one retrieval thresholds may
compare against (ADR-0005).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RankedChunk(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: int
    article_id: int
    article_slug: str
    content: str
    score: float
