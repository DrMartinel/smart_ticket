"""
The SQL each query sends. Session fakes return canned rows, so without these a
dropped filter would only show up as wrong rows in production. Assertions
target each query's purpose, not the full SQL text.
"""

from __future__ import annotations

from uuid import UUID

from ai_engine.core.state import AutoReplyProposal, LLMProposalEnvelope, RankedChunk

from ai_engine.core.config import settings
from ai_engine.core.retrieval.bm25 import bm25_search
from ai_engine.core.retrieval.vector import vector_search
from ai_engine.graph.nodes.emit_signals import emit_signals
from ai_engine.graph.nodes.fewshot import select_fewshots


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


def test_bm25_search_uses_match_disjunction_and_ranks_by_bm25_score(fake_db):
    """`|||` lets a chunk match on SOME of the ticket's words. The old
    `plainto_tsquery` required all of them in one chunk and matched nothing
    on the English golden set, silently (ADR-0013). `pdb.score` is real BM25,
    with the IDF that `ts_rank_cd` lacked.
    """

    db = fake_db()
    with db.connect() as session:
        bm25_search(session, "ERR-4042 on login")
    sql, params = _only_statement(db)

    assert "kb_chunks.content ||| %(content_1)s" in sql
    assert "kb_chunks.section_title ||| %(section_title_1)s" in sql
    assert "pdb.score(kb_chunks.id) AS score" in sql
    assert "ORDER BY score DESC" in sql
    assert "plainto_tsquery" not in sql
    assert "ts_rank" not in sql
    assert params["content_1"] == params["section_title_1"] == "ERR-4042 on login"
    assert settings.bm25_top_k in params.values()


def test_bm25_error_code_boost_is_read_from_settings(fake_db, kb_row, monkeypatch):
    """The boost is a tunable, so it lives in Settings (hard rule 2), and a
    chunk containing the ticket's error code moves ahead of one that doesn't."""

    monkeypatch.setattr(settings, "bm25_error_code_boost", 5.0)
    db = fake_db(rows=[kb_row(1, "generic text", 3.0), kb_row(2, "fix for ERR-4042", 1.0)])
    with db.connect() as session:
        hits = bm25_search(session, "ERR-4042")

    assert [h.content for h in hits] == ["fix for ERR-4042", "generic text"]
    assert hits[0].score == 6.0


def test_fewshot_selection_excludes_retracted_and_expired_examples(
    fake_db, fake_embedder, make_state, use_db, use_embedder
):
    """A retracted example (its source ticket reopened) has a suspect label;
    showing it to the model teaches the mistake. Nothing else would notice
    these filters going missing.
    """

    db = fake_db()
    use_db(db)
    use_embedder(fake_embedder(vector=[0.3]))
    select_fewshots(make_state())
    sql, params = _only_statement(db)

    assert "fewshot_examples.retracted_at IS NULL" in sql
    assert "fewshot_examples.expires_at > now()" in sql
    assert "fewshot_examples.embedding IS NOT NULL" in sql
    assert "ORDER BY fewshot_examples.embedding <=>" in sql
    assert settings.fewshot_k in params.values()


def test_kb_policy_lookup_reads_only_active_articles_by_slug(fake_db, make_state, use_db):
    """The policy lookup turns any exception into deny-by-default, so a
    broken query never surfaces as an error. This is the only place it is
    visible.
    """

    proposal = LLMProposalEnvelope(
        root=AutoReplyProposal(
            proposed_intent="auto_reply",
            kb_slug="iam.id_credentials_mfa_lost-or-broken",
            verbatim_quote="a quote long enough to be valid",
            answer_draft="draft",
            self_confidence=80.0,
        )
    )
    chunk = RankedChunk(
        chunk_id=UUID(int=1),
        article_id=UUID(int=10),
        article_slug="iam.id_credentials_mfa_lost-or-broken",
        content="content",
        score=0.9,
    )

    db = fake_db()
    use_db(db)
    emit_signals(make_state(reranked=[chunk], proposal=proposal))
    sql, params = _only_statement(db)

    assert sql.startswith("SELECT kb_articles.auto_reply_allowed, kb_articles.risk_tier")
    assert "kb_articles.slug = %(slug_1)s" in sql
    assert "kb_articles.is_active IS true" in sql
    assert params == {"slug_1": "iam.id_credentials_mfa_lost-or-broken"}
