"""Ticket categories as rows: the database guards, the seed, and the read and edit routes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.db import IntegrityError, connection, transaction

from apps.accounts.models import User, UserRole
from apps.audit.models import AuditLog
from apps.categories.domain.vocabulary import CategoryError, CategoryRefusal
from apps.categories.models import Category
from apps.tickets.models import Ticket
from infrastructure.dtos import TicketCategory

JSON = "application/json"
CATEGORY_QUESTION = (
    Path(settings.BASE_DIR).parent / "ai-engine/src/ai_engine/core/prompts/category.v2.json"
)
CATEGORY_COLUMNS = {
    ("tickets", "category"),
    ("incidents", "category"),
    ("kb_articles", "category"),
    ("kb_drafts", "category"),
    ("sla_policies", "category"),
    ("fewshot_examples", "category"),
    ("team_categories", "category"),
    ("review_decisions", "corrected_category"),
    ("team_reassignments", "from_category"),
    ("team_reassignments", "to_category"),
    ("report_ticket_facts", "category"),
}


def person(username: str, role: UserRole) -> User:
    return User.objects.create_user(
        username=username, password="x", role=role.value, email=f"{username}@example.test"
    )


def patch(client, slug: str, body: dict):
    return client.patch(f"/api/categories/{slug}", json.dumps(body), content_type=JSON)


# ── the database ──


@pytest.mark.django_db
def test_every_category_column_references_the_table():
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT kcu.table_name, kcu.column_name
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu
              ON kcu.constraint_name = rc.constraint_name
            JOIN information_schema.constraint_column_usage ccu
              ON ccu.constraint_name = rc.constraint_name
            WHERE ccu.table_name = 'ticket_categories' AND ccu.column_name = 'slug'
            """
        )
        referencing = set(cursor.fetchall())

    assert referencing == CATEGORY_COLUMNS


@pytest.mark.django_db
def test_a_ticket_with_an_unknown_category_is_refused_by_the_database():
    reporter = person("lan.nt", UserRole.EMPLOYEE)

    with pytest.raises(IntegrityError), transaction.atomic():
        Ticket.objects.create(
            public_id="TKT-CAT-000001",
            reporter=reporter,
            subject_masked="printer",
            body_masked="printer",
            pii_level="routine",
            category="billing",
        )


@pytest.mark.django_db
def test_a_category_in_use_cannot_be_deleted():
    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.filter(slug="network").delete()

    assert Category.objects.filter(slug="network").exists()


# ── the seed ──


@pytest.mark.django_db
def test_the_seeded_slugs_are_the_wire_enum():
    assert set(Category.objects.values_list("slug", flat=True)) == {c.value for c in TicketCategory}


@pytest.mark.django_db
def test_the_seeded_descriptions_are_category_v2s_criteria():
    criteria = json.loads(CATEGORY_QUESTION.read_text())["criteria"]

    seeded = dict(Category.objects.values_list("slug", "description"))

    assert seeded == {slug: c["what"] for slug, c in criteria.items()}


@pytest.mark.django_db
def test_an_inactive_category_is_refused_like_an_unknown_one():
    Category.objects.filter(slug="network").update(is_active=False)

    for slug in ("network", "billing"):
        with pytest.raises(CategoryError) as refused:
            Category.objects.require(slug)
        assert refused.value.code is CategoryRefusal.UNKNOWN_CATEGORY

    assert Category.objects.require("access").slug == "access"


@pytest.mark.django_db
def test_only_security_is_the_security_category():
    assert list(Category.objects.filter(is_security=True).values_list("slug", flat=True)) == [
        "security"
    ]


# ── reading ──


@pytest.mark.django_db
def test_an_employee_cannot_read_the_categories(api_as):
    response = api_as(person("lan.nt", UserRole.EMPLOYEE)).get("/api/categories")

    assert response.status_code == 403


@pytest.mark.django_db
def test_a_technician_reads_the_categories_in_order(api_as):
    response = api_as(person("khoa.lv", UserRole.TECHNICIAN)).get("/api/categories")

    assert response.status_code == 200
    assert [c["slug"] for c in response.json()] == [
        "hardware",
        "software",
        "network",
        "access",
        "security",
        "other",
    ]


# ── editing ──


@pytest.mark.django_db
def test_a_technician_cannot_rename_a_category(api_as):
    response = patch(
        api_as(person("khoa.lv", UserRole.TECHNICIAN)), "network", {"name": "Net", "reason": "x"}
    )

    assert response.status_code == 403
    assert Category.objects.get(slug="network").name == "Network"


@pytest.mark.django_db
def test_a_change_without_a_reason_is_refused(api_as):
    response = patch(api_as(person("huy.pq", UserRole.MANAGER)), "network", {"name": "Net"})

    assert response.status_code == 422
    assert response.json()["code"] == "reason_required"
    assert Category.objects.get(slug="network").name == "Network"


@pytest.mark.django_db
def test_an_unknown_category_is_not_found(api_as):
    response = patch(
        api_as(person("huy.pq", UserRole.MANAGER)), "billing", {"name": "Billing", "reason": "x"}
    )

    assert response.status_code == 404
    assert response.json()["code"] == "category_not_found"


@pytest.mark.django_db
def test_an_edit_cannot_change_the_description_or_flags(api_as):
    before = Category.objects.get(slug="security")

    response = patch(
        api_as(person("huy.pq", UserRole.MANAGER)),
        "security",
        {
            "name": "Security",
            "description": "anything",
            "is_security": False,
            "is_routable": False,
            "is_active": False,
            "reason": "try every field",
        },
    )

    assert response.status_code == 200
    after = Category.objects.get(slug="security")
    assert (after.description, after.is_security, after.is_routable, after.is_active) == (
        before.description,
        True,
        True,
        True,
    )


@pytest.mark.django_db
def test_a_rename_bumps_the_version_and_is_audited(api_as):
    manager = person("huy.pq", UserRole.MANAGER)

    response = patch(
        api_as(manager), "network", {"name": "Networking", "sort_order": 9, "reason": "Đổi tên"}
    )

    assert response.status_code == 200
    assert (response.json()["name"], response.json()["version"]) == ("Networking", 2)
    (audit,) = AuditLog.objects.filter(event="category_changed")
    assert audit.actor_id == manager.id
    assert audit.payload["before"] == {"name": "Network", "sort_order": 3, "version": 1}
    assert audit.payload["after"] == {"name": "Networking", "sort_order": 9, "version": 2}


@pytest.mark.django_db
def test_an_edit_that_changes_nothing_is_not_audited(api_as):
    response = patch(
        api_as(person("huy.pq", UserRole.MANAGER)), "network", {"name": "Network", "reason": "x"}
    )

    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert not AuditLog.objects.filter(event="category_changed").exists()
