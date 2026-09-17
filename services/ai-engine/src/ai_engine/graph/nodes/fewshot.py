"""
Few-shot selector — spec §6.2 `select_shots`. Reads `fewshot_examples` over
the read-only connection. The category is not known yet, so selection is
nearest-neighbour on the ticket embedding across all active examples.
"""

from __future__ import annotations

from sqlalchemy import func, select

from ai_engine.core.config import settings
from ai_engine.core.db.client import SqlAlchemySessionSource
from ai_engine.core.db.tables import FewshotExample
from ai_engine.core.node import BaseNode
from ai_engine.core.providers.base import Embedder
from ai_engine.core.state import TriageState


class SelectFewshotsNode(BaseNode):
    """A plain BaseNode, NOT a BudgetedNode: the only node that spends an
    embedding round-trip without checking the budget. See docs/TODO.md.
    """

    def __init__(self, *, db: SqlAlchemySessionSource, embedder: Embedder) -> None:
        self._db = db
        self._embedder = embedder

    def __call__(self, state: TriageState) -> dict:
        ticket = state.ticket
        query = f"{ticket.subject_masked}\n{ticket.body_masked}".strip()
        embedding = self._embedder.embed(query)

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
        with self._db.connect() as session:
            rows = session.execute(statement).all()

        fewshots = [
            {"category": category, "input_text": input_text, "output_json": output_json}
            for category, input_text, output_json in rows
        ]
        return {"fewshots": fewshots}
