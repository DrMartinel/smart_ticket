"""
KB article creation through the handler: the article row is created, then
chunked and embedded so retrieval can find it.

The two steps commit separately. If embedding fails, the article is kept
with no chunks — invisible to retrieval until `/reingest` succeeds — and the
request fails. Making creation all-or-nothing would be a behaviour change,
so it should fail here and be decided on purpose, not slip in with a
refactor.
"""

import httpx
import pytest

from apps.kb.models import KbArticle, KbChunk

ARTICLE = {
    "slug": "KB-TEST-001",
    "title": "Reset VPN password",
    "body": "Open the portal.\n\nChoose 'Reset VPN password'.\n\nSign in again.",
    "category": "network",
}


def create(client):
    return client.post("/api/kb", ARTICLE, content_type="application/json")


@pytest.mark.django_db
def test_created_article_is_chunked_and_embedded(manager_user, api_as):
    response = create(api_as(manager_user))

    article = KbArticle.objects.get(slug="KB-TEST-001")
    assert response.json()["id"] == str(article.id)
    chunks = KbChunk.objects.filter(article=article)
    assert chunks.count() >= 1
    assert all(c.embedding is not None and len(c.embedding) == 1024 for c in chunks)
    # Creation never grants auto-reply authority; that goes through
    # set_auto_reply_allowed with a manager, a reason and a log row.
    assert article.auto_reply_allowed is False
    assert article.risk_tier == "high"


@pytest.mark.django_db
def test_embedding_failure_keeps_the_article_without_chunks(manager_user, serve_ai_engine, api_as):
    def unreachable(request):
        raise httpx.ConnectError("ai-engine unreachable")

    serve_ai_engine(unreachable)

    with pytest.raises(httpx.ConnectError):
        create(api_as(manager_user))

    article = KbArticle.objects.get(slug="KB-TEST-001")
    assert not KbChunk.objects.filter(article=article).exists()
