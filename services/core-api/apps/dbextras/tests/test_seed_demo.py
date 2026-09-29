"""
`seed_demo` pre-approves some KB articles for auto-reply. It must do that
through the same governance path a manager uses (ADR-0002): a manager
actor, a non-empty reason, and a `KbAuthorityLog` row per change.

Seed data is the first thing anyone sees. If it flips `auto_reply_allowed`
directly, every demo database starts with auto-reply authority that no audit
trail explains, and the seed teaches the pattern the governance path exists
to forbid.
"""

from io import StringIO

import pytest
from django.core.management import call_command

from apps.accounts.models import User
from apps.kb.models import KbArticle, KbAuthorityLog


@pytest.fixture
def seeded(settings):
    settings.EMBEDDING_PROVIDER = "stub"
    call_command("seed_demo", stdout=StringIO())


@pytest.mark.django_db
def test_every_auto_reply_approval_has_an_authority_log_row(seeded):
    approved = KbArticle.objects.filter(auto_reply_allowed=True)
    assert approved.exists(), "seed no longer approves any article; update this test"

    manager = User.objects.get(username="manager1")
    for article in approved:
        logs = KbAuthorityLog.objects.filter(article=article, field="auto_reply_allowed")
        assert logs.count() == 1, article.slug
        log = logs.get()
        assert log.new_value == "True"
        assert log.actor == manager
        assert log.reason.strip()
        assert article.approved_by == manager


@pytest.mark.django_db
def test_unapproved_articles_have_no_authority_log_rows(seeded):
    unapproved = KbArticle.objects.filter(auto_reply_allowed=False)
    assert not KbAuthorityLog.objects.filter(article__in=unapproved).exists()
