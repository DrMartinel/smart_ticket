"""Ticket categories as rows: the database guards, the seed, and the read and edit routes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from django.conf import settings
from django.db import IntegrityError, connection, transaction

from apps.accounts.models import User, UserRole
from apps.accounts.testing import grant_capability
from apps.audit.models import AuditLog
from apps.categories.domain.vocabulary import CategoryError, CategoryRefusal
from apps.categories.models import Category
from apps.tickets.models import Ticket

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
    Category.objects.create(slug="billing", name="Billing", description="Invoices.")
    Ticket.objects.create(
        public_id="TKT-CAT-000002",
        reporter=person("lan.nt", UserRole.EMPLOYEE),
        subject_masked="invoice",
        body_masked="invoice",
        pii_level="routine",
        category="billing",
    )

    with pytest.raises(IntegrityError), transaction.atomic():
        Category.objects.filter(slug="billing").delete()

    assert Category.objects.filter(slug="billing").exists()


# ── the seed ──


@pytest.mark.django_db
def test_the_seeded_slugs_are_the_wire_enum():
    assert set(Category.objects.values_list("slug", flat=True)) == {
        "hardware",
        "software",
        "network",
        "access",
        "security",
        "other",
    }


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
@pytest.mark.parametrize(
    "field, value",
    [
        ("is_security", False),
        ("is_active", False),
        ("slug", "sec"),
    ],
)
def test_an_edit_of_the_slug_or_a_locked_flag_is_refused(api_as, field, value):
    before = Category.objects.get(slug="security")

    response = patch(
        api_as(person("huy.pq", UserRole.MANAGER)),
        "security",
        {"name": "Security team", field: value, "reason": "try a locked field"},
    )

    assert response.status_code == 422
    after = Category.objects.get(slug="security")
    assert (after.name, after.description, after.is_security, after.is_routable) == (
        "Security",
        before.description,
        True,
        True,
    )
    assert (after.is_active, after.version) == (True, 1)


@pytest.mark.django_db
def test_a_blank_name_is_refused(api_as):
    response = patch(
        api_as(person("huy.pq", UserRole.MANAGER)), "network", {"name": "   ", "reason": "x"}
    )

    assert response.status_code == 422
    assert Category.objects.get(slug="network").name == "Network"


@pytest.mark.django_db
def test_a_name_is_stored_without_surrounding_spaces(api_as):
    response = patch(
        api_as(person("huy.pq", UserRole.MANAGER)),
        "network",
        {"name": "  Networking  ", "reason": "Đổi tên"},
    )

    assert response.status_code == 200
    assert Category.objects.get(slug="network").name == "Networking"


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
    assert audit.payload["before"]["name"] == "Network"
    assert audit.payload["after"]["name"] == "Networking"
    assert (audit.payload["before"]["sort_order"], audit.payload["after"]["sort_order"]) == (3, 9)
    assert (audit.payload["before"]["version"], audit.payload["after"]["version"]) == (1, 2)


@pytest.mark.django_db
def test_an_edit_that_changes_nothing_is_not_audited(api_as):
    response = patch(
        api_as(person("huy.pq", UserRole.MANAGER)), "network", {"name": "Network", "reason": "x"}
    )

    assert response.status_code == 200
    assert response.json()["version"] == 1
    assert not AuditLog.objects.filter(event="category_changed").exists()


# ── a manager's description and routing (open questions 1 and 2) ──


@pytest.mark.django_db
def test_a_managers_description_change_keeps_both_texts_in_the_audit(api_as):
    manager = person("huy.pq", UserRole.MANAGER)
    before = Category.objects.get(slug="network").description

    response = patch(
        api_as(manager),
        "network",
        {"description": "  Connectivity, now with Direct Connect.  ", "reason": "new service"},
    )

    assert response.status_code == 200
    assert response.json()["description"] == "Connectivity, now with Direct Connect."
    assert response.json()["version"] == 2
    (audit,) = AuditLog.objects.filter(event="category_changed")
    assert audit.payload["before"]["description"] == before
    assert audit.payload["after"]["description"] == "Connectivity, now with Direct Connect."
    assert audit.payload["reason"] == "new service"


@pytest.mark.django_db
def test_a_manager_turns_routing_off_with_a_reason(api_as):
    response = patch(
        api_as(person("huy.pq", UserRole.MANAGER)),
        "network",
        {"is_routable": False, "reason": "per-category F1 below the floor"},
    )

    assert response.status_code == 200
    assert Category.objects.get(slug="network").is_routable is False
    (audit,) = AuditLog.objects.filter(event="category_changed")
    assert (audit.payload["before"]["is_routable"], audit.payload["after"]["is_routable"]) == (
        True,
        False,
    )


@pytest.mark.django_db
@pytest.mark.parametrize("field, value", [("description", "Connectivity."), ("is_routable", False)])
def test_a_workflow_admin_renames_but_cannot_change_what_a_category_means(api_as, field, value):
    admin = person("tu.dv", UserRole.TECHNICIAN)
    grant_capability(admin, "workflow_admin")
    before = Category.objects.get(slug="network")

    response = patch(api_as(admin), "network", {"name": "Net", field: value, "reason": "x"})

    assert response.status_code == 403
    assert response.json()["code"] == "not_allowed"
    after = Category.objects.get(slug="network")
    assert (after.name, after.description, after.is_routable, after.version) == (
        "Network",
        before.description,
        True,
        1,
    )
    assert not AuditLog.objects.filter(event="category_changed").exists()


@pytest.mark.django_db
def test_a_workflow_admin_still_renames_a_category(api_as):
    admin = person("tu.dv", UserRole.TECHNICIAN)
    grant_capability(admin, "workflow_admin")

    response = patch(api_as(admin), "network", {"name": "Networking", "reason": "x"})

    assert response.status_code == 200
    assert Category.objects.get(slug="network").name == "Networking"


@pytest.mark.django_db
def test_a_blank_description_is_refused(api_as):
    response = patch(
        api_as(person("huy.pq", UserRole.MANAGER)), "network", {"description": "  ", "reason": "x"}
    )

    assert response.status_code == 422
    assert Category.objects.get(slug="network").version == 1


@pytest.mark.django_db
@pytest.mark.parametrize(
    "slug, expected", [("security", True), ("network", False), (None, False), ("billing", False)]
)
def test_security_is_the_flag_not_the_slug(slug, expected):
    assert Category.objects.is_security(slug) is expected


@pytest.mark.django_db
def test_a_security_category_by_another_slug_counts_as_security():
    Category.objects.filter(slug="security").update(is_security=False)
    Category.objects.create(slug="secops", name="SecOps", description="d", is_security=True)

    assert Category.objects.is_security("secops")
    assert not Category.objects.is_security("security")
