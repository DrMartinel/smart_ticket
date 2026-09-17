"""
The SQL each query sends. Session fakes return canned rows, so without these a
dropped filter would only show up as wrong rows in production. Assertions
target each query's purpose, not the full SQL text.
"""

from __future__ import annotations

from contracts.llm_draft import AutoReplyProposal, LLMProposalEnvelope

from ai_engine.core.config import settings
from ai_engine.core.retrieval.bm25 import bm25_search
from ai_engine.core.retrieval.vector import vector_search
from ai_engine.graph.nodes.emit_signals import EmitSignalsNode
from ai_engine.graph.nodes.fewshot import SelectFewshotsNode
from ai_engine.graph.nodes.rerank import RankedChunk


def _only_statement(db) -> tuple[str, dict]:
    [session] = db.sessions
    [(sql, params)] = session.executed
    return " ".join(sql.split()), params


def test_vector_search_orders_by_cosine_distance_over_embedded_chunks_only(fake_db):
    """ORDER BY must be the bare `<=>` expression the HNSW index can serve.
    Ordering by the derived similarity still returns correct rows, via a
    full scan — a silent latency regression.
    """

    db = fake_db()
    with db.connect() as session:
        vector_search(session, [0.1, 0.2])
    sql, params = _only_statement(db)

    assert "kb_chunks.embedding IS NOT NULL" in sql
    assert "ORDER BY kb_chunks.embedding <=> %(embedding_1)s" in sql
    assert "JOIN kb_articles ON kb_articles.id = kb_chunks.article_id" in sql
    assert params["embedding_1"] == [0.1, 0.2]
    assert settings.vector_top_k in params.values()


def test_bm25_search_matches_and_ranks_on_tsv_with_the_simple_config(fake_db):
    """The query config must be 'simple' to match the tsv trigger
    (0003_constraints_and_triggers.sql). A mismatch returns no rows rather
    than an error, which reads as "the KB has nothing relevant".
    """

    db = fake_db()
    with db.connect() as session:
        bm25_search(session, "ERR-4042")
    sql, params = _only_statement(db)

    assert "kb_chunks.tsv @@ plainto_tsquery(" in sql
    assert "ts_rank_cd(kb_chunks.tsv, plainto_tsquery(" in sql
    assert "ORDER BY score DESC" in sql
    assert "simple" in params.values()
    assert "ERR-4042" in params.values()
    assert settings.bm25_top_k in params.values()


def test_fewshot_selection_excludes_retracted_and_expired_examples(
    fake_db, fake_embedder, make_state
):
    """A retracted example (its source ticket reopened) has a suspect label;
    showing it to the model teaches the mistake. Nothing else would notice
    these filters going missing.
    """

    db = fake_db()
    SelectFewshotsNode(db=db, embedder=fake_embedder(vector=[0.3]))(make_state())
    sql, params = _only_statement(db)

    assert "fewshot_examples.retracted_at IS NULL" in sql
    assert "fewshot_examples.expires_at > now()" in sql
    assert "fewshot_examples.embedding IS NOT NULL" in sql
    assert "ORDER BY fewshot_examples.embedding <=>" in sql
    assert settings.fewshot_k in params.values()


def test_kb_policy_lookup_reads_only_active_articles_by_slug(fake_db, make_state):
    """The policy lookup turns any exception into deny-by-default, so a
    broken query never surfaces as an error. This is the only place it is
    visible.
    """

    proposal = LLMProposalEnvelope(
        root=AutoReplyProposal(
            proposed_intent="auto_reply",
            kb_slug="KB-0142",
            verbatim_quote="một đoạn trích đủ dài để hợp lệ",
            answer_draft="draft",
            self_confidence=80.0,
        )
    )
    chunk = RankedChunk(
        chunk_id=1, article_id=10, article_slug="KB-0142", content="nội dung", score=0.9
    )

    db = fake_db()
    EmitSignalsNode(db=db)(make_state(reranked=[chunk], proposal=proposal))
    sql, params = _only_statement(db)

    assert sql.startswith("SELECT kb_articles.auto_reply_allowed, kb_articles.risk_tier")
    assert "kb_articles.slug = %(slug_1)s" in sql
    assert "kb_articles.is_active IS true" in sql
    assert params == {"slug_1": "KB-0142"}
