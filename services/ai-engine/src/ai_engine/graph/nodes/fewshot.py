"""
Few-shot selector — spec §6.2 `select_shots`. Reads `fewshot_examples` over
the read-only connection. The category is not known yet, so selection is
nearest-neighbour on the ticket embedding across all active examples.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from ai_engine.core.config import settings
from ai_engine.core.db.client import db
from ai_engine.core.db.tables import FewshotExample
from ai_engine.graph.build.node import BaseNode
from ai_engine.graph.state import TriageState


class SelectFewshotsNode(BaseNode):
    def __call__(self, state: TriageState) -> dict[str, Any]:
        # The embedding HybridRetrieveNode made of the same ticket text: one
        # embed call per ticket, not two.
        embedding = state.query_embedding

        # Retracted (source ticket reopened, so its label is suspect) and
        # expired examples are not in the pool: the model would learn from them.
        statement = (
            select(FewshotExample.category, FewshotExample.input_text, FewshotExample.output_json)
            .where(
                FewshotExample.retracted_at.is_(None),
                FewshotExample.expires_at > func.now(),
                FewshotExample.embedding.is_not(None),
            )
            .order_by(FewshotExample.embedding.cosine_distance(embedding))
            .limit(settings.fewshot_k)
        )
        rows = db.all(statement)

        fewshots = [
            {"category": category, "input_text": input_text, "output_json": output_json}
            for category, input_text, output_json in rows
        ]
        return {"fewshots": fewshots}


select_fewshots = SelectFewshotsNode()
