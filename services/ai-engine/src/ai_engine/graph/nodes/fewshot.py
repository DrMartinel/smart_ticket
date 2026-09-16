"""
Few-shot selector — spec §6.2 node `select_shots` (graph node
`select_fewshots`). Reads `fewshot_examples` through the same read-only
connection as KB retrieval (ai_engine_ro has SELECT on exactly this table
plus kb_articles/kb_chunks — nothing else). Category isn't known yet at
this point in the pipeline (that's what inference is about to determine),
so selection is by nearest neighbor on the ticket embedding across all
active examples, not by an exact category filter.
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
    """Note this node is a plain BaseNode, NOT a BudgetedNode like
    retrieve/rerank/infer — carried over from the original as-is rather than
    changed inside a refactor, but see docs/TODO.md: it is the only node that
    spends an embedding round-trip without first checking the ticket's budget.
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
