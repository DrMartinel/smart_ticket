"""
KB endpoints over HTTP. The response schema decides what the web receives,
so the article's keys are pinned here. `approved_by` is read from the
`approved_by_id` column under its old name; if that mapping breaks, the KB
page shows no approver while the database has one.
"""

import pytest

from apps.kb.models import KbArticle

ARTICLE_KEYS = {
    "id",
    "slug",
    "title",
    "category",
    "source_url",
    "auto_reply_allowed",
    "risk_tier",
    "approved_by",
    "is_active",
    "version",
}


@pytest.fixture
def article():
    return KbArticle.objects.create(
        slug="KB-API-001", title="VPN", body="Step one.\n\nStep two.", category="network"
    )


@pytest.mark.django_db
def test_articles_are_listed(article, technician_user, api_as):
    response = api_as(technician_user).get("/api/kb")

    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    [row] = body["items"]
    assert set(row) == ARTICLE_KEYS
    assert row["slug"] == "KB-API-001"
    assert row["approved_by"] is None


@pytest.mark.django_db
def test_articles_are_searched_filtered_and_paginated(technician_user, api_as):
    """The demo KB has thousands of articles; the list must narrow them on
    the server, not ship every row to the browser."""
    for slug, title, category in [
        ("iam.mfa", "Using MFA", "access"),
        ("iam.roles", "IAM roles", "access"),
        ("vpc.nat", "NAT gateways", "network"),
    ]:
        KbArticle.objects.create(slug=slug, title=title, body="x", category=category)
    client = api_as(technician_user)

    assert client.get("/api/kb?q=mfa").json()["count"] == 1
    assert client.get("/api/kb?category=access").json()["count"] == 2
    page = client.get("/api/kb?limit=2&offset=0").json()
    assert page["count"] == 3
    assert [a["slug"] for a in page["items"]] == ["iam.mfa", "iam.roles"]


@pytest.mark.django_db
def test_approving_auto_reply_returns_the_approver(article, manager_user, api_as):
    response = api_as(manager_user).post(
        "/api/kb/KB-API-001/auto-reply-allowed",
        {"allowed": True, "reason": "low risk, checked"},
        content_type="application/json",
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == ARTICLE_KEYS
    assert body["auto_reply_allowed"] is True
    assert body["approved_by"] == str(manager_user.id)
    assert body["version"] == 2


@pytest.mark.django_db
def test_a_non_manager_cannot_approve_auto_reply(article, technician_user, api_as):
    response = api_as(technician_user).post(
        "/api/kb/KB-API-001/auto-reply-allowed",
        {"allowed": True, "reason": "please"},
        content_type="application/json",
    )

    assert response.status_code == 403
    article.refresh_from_db()
    assert article.auto_reply_allowed is False


@pytest.mark.django_db
def test_changing_the_risk_tier_returns_the_article(article, manager_user, api_as):
    response = api_as(manager_user).post(
        "/api/kb/KB-API-001/risk-tier",
        {"risk_tier": "medium", "reason": "reviewed"},
        content_type="application/json",
    )

    assert response.status_code == 200
    assert set(response.json()) == ARTICLE_KEYS
    assert response.json()["risk_tier"] == "medium"


@pytest.mark.django_db
def test_reingest_returns_the_chunk_count(article, manager_user, api_as):
    response = api_as(manager_user).post("/api/kb/KB-API-001/reingest")

    assert response.status_code == 200
    assert response.json() == {"slug": "KB-API-001", "chunks": 1}
