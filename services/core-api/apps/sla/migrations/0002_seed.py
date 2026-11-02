"""Seeds the VN office calendar, its holidays and the five policies of F1 §g, all active."""

from datetime import date, timedelta

from django.db import migrations

OFFICE_HOURS = {day: [["08:00", "17:30"]] for day in ("mon", "tue", "wed", "thu", "fri")}

# date (or first, last), name: F1 §g as it shipped; HR confirms each year (OQ-13).
HOLIDAYS = [
    (date(2026, 11, 24), date(2026, 11, 24), "Ngày Văn hoá Việt Nam"),
    (date(2027, 1, 1), date(2027, 1, 1), "Tết Dương lịch"),
    (date(2027, 2, 4), date(2027, 2, 10), "Tết Nguyên đán"),
    (date(2027, 4, 16), date(2027, 4, 16), "Giỗ Tổ Hùng Vương"),
    (date(2027, 4, 30), date(2027, 4, 30), "Ngày Giải phóng miền Nam"),
    (date(2027, 5, 3), date(2027, 5, 3), "Quốc tế Lao động (nghỉ bù)"),
    (date(2027, 9, 2), date(2027, 9, 3), "Quốc khánh"),
]

# order, name, priority, response, resolution (business minutes), 24x7
POLICIES = [
    (10, "P1 — critical", "P1", 15, 240, True),
    (20, "P2 — high", "P2", 30, 480, False),
    (30, "P3 — normal", "P3", 240, 1710, False),
    (40, "P4 — low", "P4", 570, 2850, False),
    (999, "Default", None, 240, 1710, False),
]


def seed(apps, schema_editor):
    Calendar = apps.get_model("sla", "Calendar")
    Holiday = apps.get_model("sla", "Holiday")
    Policy = apps.get_model("sla", "Policy")
    office, _ = Calendar.objects.get_or_create(
        name="VN office",
        defaults={
            "timezone": "Asia/Ho_Chi_Minh",
            "working_hours": OFFICE_HOURS,
            "is_default": not Calendar.objects.filter(is_default=True).exists(),
        },
    )
    for first, last, name in HOLIDAYS:
        day = first
        while day <= last:
            Holiday.objects.get_or_create(calendar=office, date=day, defaults={"name": name})
            day += timedelta(days=1)
    if Policy.objects.exists():
        return
    for order, name, priority, response, resolution, is_24x7 in POLICIES:
        Policy.objects.create(
            name=name,
            order=order,
            priority=priority,
            response_minutes=response,
            resolution_minutes=resolution,
            calendar=None if is_24x7 else office,
            is_24x7=is_24x7,
            state="active",
        )


def unseed(apps, schema_editor):
    apps.get_model("sla", "Policy").objects.filter(created_by__isnull=True).delete()
    apps.get_model("sla", "Calendar").objects.filter(name="VN office").delete()


class Migration(migrations.Migration):
    dependencies = [("sla", "0001_initial")]

    operations = [migrations.RunPython(seed, unseed)]
