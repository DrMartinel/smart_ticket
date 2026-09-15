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

from ai_engine.core.config import settings
from ai_engine.core.node import BaseNode
from ai_engine.core.protocols import ConnectionSource, Embedder
from ai_engine.core.state import TriageState
from ai_engine.retrieval.vector import to_vector_literal


class SelectFewshotsNode(BaseNode):
    """Note this node is a plain BaseNode, NOT a BudgetedNode like
    retrieve/rerank/infer — carried over from the original as-is rather than
    changed inside a refactor, but see docs/TODO.md: it is the only node that
    spends an embedding round-trip without first checking the ticket's budget.
    """

    def __init__(self, *, db: ConnectionSource, embedder: Embedder) -> None:
        self._db = db
        self._embedder = embedder

    def __call__(self, state: TriageState) -> dict:
        ticket = state["ticket"]
        query = f"{ticket.subject_masked}\n{ticket.body_masked}".strip()
        embedding = self._embedder.embed(query)
        literal = to_vector_literal(embedding)

        with self._db.connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                SELECT category, input_text, output_json
                FROM fewshot_examples
                WHERE retracted_at IS NULL AND expires_at > now() AND embedding IS NOT NULL
                ORDER BY embedding <=> %(v)s::vector
                LIMIT %(k)s
                """,
                {"v": literal, "k": settings.fewshot_k},
            )
            rows = cur.fetchall()

        fewshots = [
            {"category": category, "input_text": input_text, "output_json": output_json}
            for category, input_text, output_json in rows
        ]
        return {"fewshots": fewshots}
