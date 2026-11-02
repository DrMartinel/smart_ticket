"""SLA endpoints: policies with approval, calendars, holidays, preview, ticket clocks, breaches (F1)."""

from __future__ import annotations

import json

from apps.accounts.models import Capability, UserCapability
from apps.audit.models import AuditLog
from apps.sla.models import Calendar, Holiday, Policy
from apps.sla.tests.conftest import handed_off
from apps.sla.utils.clocks import sla_clocks

JSON = "application/json"

P3_FASTER = {
    "name": "P3 — faster",
    "order": 25,
    "priority": "P3",
    "response_minutes": 120,
    "resolution_minutes": 1140,
}


def send(client, method: str, url: str, body: dict):
    return getattr(client, method)(url, json.dumps(body), content_type=JSON)


def admin(person):
    UserCapability.objects.create(user=person, capability=Capability.WORKFLOW_ADMIN.value)
    return person


def test_a_manager_cannot_approve_their_own_draft(people, api_as):
    """AC-F1-08."""
    huy = admin(people["huy"])
    draft = send(api_as(huy), "post", "/api/sla/policies", P3_FASTER).json()

    response = send(
        api_as(huy), "post", f"/api/sla/policies/{draft['id']}/approve", {"reason": "ok"}
    )

    assert response.status_code == 403
    assert response.json()["code"] == "self_approval"
    assert Policy.objects.get(pk=draft["id"]).state == "draft"


def test_another_manager_activates_a_draft_with_a_reason(people, api_as):
    draft = send(api_as(admin(people["tu"])), "post", "/api/sla/policies", P3_FASTER).json()

    response = send(
        api_as(people["huy"]), "post", f"/api/sla/policies/{draft['id']}/approve", {"reason": "Q4"}
    )

    assert response.json()["state"] == "active"
    assert AuditLog.objects.get(event="sla_policy_activated").payload["reason"] == "Q4"


def test_a_draft_taking_an_active_order_is_refused_on_approval(people, api_as):
    body = {**P3_FASTER, "order": 30}
    draft = send(api_as(admin(people["tu"])), "post", "/api/sla/policies", body).json()

    response = send(
        api_as(people["huy"]), "post", f"/api/sla/policies/{draft['id']}/approve", {"reason": "x"}
    )

    assert response.json()["code"] == "order_taken"


def test_a_response_target_above_the_resolution_target_is_refused(people, api_as):
    response = send(
        api_as(admin(people["tu"])),
        "post",
        "/api/sla/policies",
        {**P3_FASTER, "response_minutes": 2000},
    )

    assert response.json()["code"] == "invalid_target"


def test_the_default_policy_cannot_be_retired(people, api_as):
    default = Policy.objects.get(name="Default")

    response = send(
        api_as(people["huy"]), "post", f"/api/sla/policies/{default.id}/retire", {"reason": "x"}
    )

    assert response.json()["code"] == "default_policy"


def test_an_active_policy_is_not_edited_in_place(people, api_as):
    p3 = Policy.objects.get(name="P3 — normal")

    response = send(
        api_as(admin(people["tu"])),
        "patch",
        f"/api/sla/policies/{p3.id}",
        {"resolution_minutes": 1},
    )

    assert response.json()["code"] == "not_a_draft"


def test_a_technician_cannot_draft_a_policy(people, api_as):
    assert send(api_as(people["mai"]), "post", "/api/sla/policies", P3_FASTER).status_code == 403


def test_a_calendar_with_a_bad_interval_or_zone_is_refused(people, api_as):
    client = api_as(admin(people["tu"]))
    base = {"name": "Night shift", "timezone": "Asia/Ho_Chi_Minh"}

    bad_hours = send(
        client,
        "post",
        "/api/sla/calendars",
        {**base, "working_hours": {"mon": [["18:00", "06:00"]]}},
    )
    bad_zone = send(
        client,
        "post",
        "/api/sla/calendars",
        {**base, "timezone": "Asia/Hanoi", "working_hours": {"mon": [["08:00", "17:00"]]}},
    )

    assert bad_hours.json()["code"] == "bad_interval"
    assert bad_zone.json()["code"] == "unknown_timezone"


def test_tet_is_added_as_a_range_and_a_repeat_is_refused(people, api_as):
    client = api_as(admin(people["tu"]))
    office = Calendar.objects.get(name="VN office")
    url = f"/api/sla/calendars/{office.id}/holidays"

    added = send(
        client, "post", url, {"from": "2028-01-25", "to": "2028-01-31", "name": "Tết Nguyên đán"}
    )
    again = send(client, "post", url, {"date": "2028-01-27", "name": "Tết"})

    assert added.status_code == 201 and len(added.json()) == 7
    assert again.json()["code"] == "holiday_exists"
    assert Holiday.objects.filter(calendar=office, date__year=2028).count() == 7


def test_the_preview_shows_due_times_without_creating_clocks(people, api_as):
    """FR-F1-014: §g's worked example as a preview."""
    response = send(
        api_as(people["mai"]),
        "post",
        "/api/sla/preview",
        {"category": "hardware", "priority": "P3", "start_at": "2026-10-23T08:30:00Z"},
    )

    body = response.json()
    assert body["policy"] == "P3 — normal"
    assert body["response"]["due_at"] == "2026-10-26T03:00:00Z"
    assert body["resolution"]["due_at"] == "2026-10-28T08:30:00Z"


def test_staff_see_the_clocks_and_the_requester_only_the_resolution_due(clock, people, api_as):
    clock.set(2026, 10, 23, 15, 30)
    ticket = handed_off(people["lan"], category="hardware")
    clock.set(2026, 10, 28, 11, 0)

    staff = api_as(people["mai"]).get(f"/api/tickets/{ticket.public_id}/sla").json()
    requester = api_as(people["lan"]).get(f"/api/tickets/{ticket.public_id}/sla").json()

    assert staff["priority"] == "P3" and staff["policy"] == "P3 — normal"
    resolution = next(c for c in staff["clocks"] if c["kind"] == "resolution")
    assert resolution["target_minutes"] == 1710
    assert resolution["elapsed_minutes"] == 120 + 570 + 570 + 180
    assert [c["kind"] for c in requester["clocks"]] == ["resolution"]
    assert requester["policy"] is None and requester["clocks"][0]["target_minutes"] == 0


def test_the_breach_list_shows_warned_and_breached_clocks(clock, people, api_as):
    clock.set(2026, 10, 26, 8, 0)
    ticket = handed_off(people["lan"], category="security")
    clock.set(2026, 10, 26, 8, 25)
    sla_clocks.sweep()
    clock.set(2026, 10, 26, 8, 31)
    sla_clocks.sweep()

    rows = api_as(people["mai"]).get("/api/sla/breaches?state=breached").json()["items"]

    assert [(r["ticket"], r["kind"]) for r in rows] == [(ticket.public_id, "response")]
    assert rows[0]["breached_at"].startswith("2026-10-26T01:30:00")


def test_only_a_manager_rebuilds_clocks(clock, people, api_as):
    ticket = handed_off(people["lan"], category="hardware")
    url = f"/api/tickets/{ticket.public_id}/sla/rebuild"

    refused = api_as(people["mai"]).post(url)
    rebuilt = api_as(people["huy"]).post(url)

    assert refused.status_code == 403
    assert rebuilt.status_code == 200
    assert {c["state"] for c in rebuilt.json()["clocks"]} == {"running"}
    assert AuditLog.objects.filter(event="sla_rebuilt").count() == 1
