"""
`linked_article_ids` reads `kb_article_associations` (ADR-0018). The fake
session answers with canned rows, so these pin two things separately: the
SQL (which source, active targets only, ranked per seed by score) and what
the function does with the rows (seed order, de-duplication, the cap).
A dropped `is_active` join would not fail loudly: it would only send
retired pages to the cross-encoder.
"""

from __future__ import annotations

import uuid

import pytest

from ai_engine.core.config import settings
from ai_engine.graph.nodes.candidate_pool.links import linked_article_ids

SEED_A, SEED_B = uuid.UUID(int=1), uuid.UUID(int=2)
T1, T2, T3 = uuid.UUID(int=11), uuid.UUID(int=12), uuid.UUID(int=13)


@pytest.fixture
def source(monkeypatch):
    def use(name: str) -> None:
        monkeypatch.setattr(settings, "association_source", name)

    return use


def _sql(db) -> tuple[str, dict]:
    [session] = db.sessions
    [(sql, params)] = session.executed
    return " ".join(sql.split()), params


def test_reads_one_source_active_targets_ranked_by_score_per_seed(fake_db, source, use_db):
    source("entity_graph")
    db = use_db(fake_db())

    linked_article_ids([SEED_A], max_per_seed=3)
    sql, params = _sql(db)

    assert "FROM kb_article_associations JOIN kb_articles" in sql
    assert "kb_articles.id = kb_article_associations.target_article_id" in sql
    assert "kb_articles.is_active IS true" in sql
    assert (
        "PARTITION BY kb_article_associations.source_article_id ORDER BY "
        "kb_article_associations.score DESC, kb_article_associations.target_article_id" in sql
    )
    assert "entity_graph" in params.values()
    assert 3 in params.values()


def test_seed_order_then_score_order_each_target_once(fake_db, source, use_db):
    """Rows come back grouped by seed id, not in the seeds' order: the
    function must restore the cross-encoder's seed order, and keep a target
    two seeds share only where it first appears."""
    source("authored_link")
    use_db(fake_db([(SEED_A, T2, 0.9), (SEED_A, T3, 0.5), (SEED_B, T1, 0.8), (SEED_B, T2, 0.4)]))

    assert linked_article_ids([SEED_B, SEED_A], max_per_seed=2) == [T1, T2, T3]


def test_a_self_pair_is_never_followed(fake_db, source, use_db):
    source("authored_link")
    use_db(fake_db([(SEED_A, SEED_A, 1.0), (SEED_A, T1, 0.5)]))

    assert linked_article_ids([SEED_A], max_per_seed=5) == [T1]


def test_source_none_returns_nothing_without_a_query(fake_db, source, use_db):
    """R0 in the eval: expansion off. Not a query that happens to find
    nothing, which would still cost a round trip per ticket."""
    source("none")
    db = use_db(fake_db([(SEED_A, T1, 1.0)]))

    assert linked_article_ids([SEED_A], max_per_seed=5) == []
    assert db.sessions == []


def test_no_seeds_returns_nothing_without_a_query(fake_db, source, use_db):
    source("authored_link")
    db = use_db(fake_db())

    assert linked_article_ids([], max_per_seed=5) == []
    assert db.sessions == []
