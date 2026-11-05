"""CSV import of departments and people, tried as a whole first and applied only when every row
passes (FR-F14-005)."""

from __future__ import annotations

import csv
import io
from collections.abc import Callable
from dataclasses import dataclass, field

from django.conf import settings
from django.db import transaction

from apps.accounts.models import Department, User
from apps.accounts.utils.departments import DepartmentDraft, departments
from apps.accounts.utils.grants import require_reason
from apps.accounts.utils.people import Profile, people
from apps.accounts.utils.vocabulary import OrgError, OrgRefusal

DEPARTMENT_COLUMNS = ("code", "name", "parent_code", "head", "cost_centre")
PEOPLE_COLUMNS = (
    "username",
    "email",
    "first_name",
    "last_name",
    "department_code",
    "line_manager",
    "job_title",
    "location",
    "phone",
    "employee_id",
)


@dataclass
class ImportRow:
    """What one CSV line does, or why it can't."""

    line: int
    key: str
    action: str = "unchanged"
    errors: list[str] = field(default_factory=list)


@dataclass
class ImportResult:
    applied: bool
    rows: list[ImportRow]


class RolledBack(Exception):
    """Undoes a dry run or a file with a failing row."""


class OrgImport:
    """Reads a CSV of departments or people and applies it in one transaction."""

    def departments(self, actor: User, text: str, reason: str, *, dry_run: bool) -> ImportResult:
        reason = require_reason(reason)
        lines = self.read(text, required=("code", "name"))
        codes = {row["code"].strip().upper() for _, row in lines}
        ordered = self.parents_first(lines, codes)
        return self.run(ordered, lambda row: self.department_row(actor, row, reason), dry_run)

    def people(self, actor: User, text: str, reason: str, *, dry_run: bool) -> ImportResult:
        reason = require_reason(reason)
        lines = self.read(text, required=("username",))
        return self.run(lines, lambda row: self.person_row(actor, row, reason), dry_run)

    def run(
        self,
        lines: list[tuple[int, dict[str, str]]],
        apply: Callable[[dict[str, str]], tuple[str, str]],
        dry_run: bool,
    ) -> ImportResult:
        """Applies every line in one transaction, undone on a dry run or any failing line."""
        rows: list[ImportRow] = []
        try:
            with transaction.atomic():
                for number, line in lines:
                    row = ImportRow(number, next(iter(line.values()), "").strip())
                    try:
                        with transaction.atomic():
                            row.key, row.action = apply(line)
                    except OrgError as refused:
                        row.errors.append(f"{refused.code.value}: {refused.message}")
                    rows.append(row)
                if dry_run or any(r.errors for r in rows):
                    raise RolledBack
        except RolledBack:
            return ImportResult(applied=False, rows=sorted(rows, key=lambda r: r.line))
        return ImportResult(applied=True, rows=sorted(rows, key=lambda r: r.line))

    def department_row(self, actor: User, line: dict[str, str], reason: str) -> tuple[str, str]:
        code = line["code"].strip().upper()
        parent = (line.get("parent_code") or "").strip().upper() or None
        draft = DepartmentDraft(
            name=line.get("name", "").strip(),
            head=(line.get("head") or "").strip() or None,
            cost_centre=(line.get("cost_centre") or "").strip(),
        )
        existing = Department.objects.filter(code=code).first()
        if existing is None:
            departments.create(
                actor,
                code,
                DepartmentDraft(draft.name, parent, draft.head, draft.cost_centre),
                reason,
            )
            return code, "create"
        before = departments.snapshot(existing)
        departments.update(actor, code, draft, reason)
        if (existing.parent.code if existing.parent else None) != parent:
            departments.move(actor, code, parent, reason)
        existing.refresh_from_db()
        return code, "update" if departments.snapshot(existing) != before else "unchanged"

    def person_row(self, actor: User, line: dict[str, str], reason: str) -> tuple[str, str]:
        username = line["username"].strip()
        profile = Profile(
            **{
                name: (line.get(name) or "").strip() or None
                for name in ("first_name", "last_name", "job_title", "location", "phone")
            },
            employee_id=(line.get("employee_id") or "").strip() or None,
            department=(line.get("department_code") or "").strip() or None,
            line_manager=(line.get("line_manager") or "").strip() or None,
        )
        existing = User.objects.filter(username=username).first()
        if existing is None:
            email = (line.get("email") or "").strip()
            if not email:
                raise OrgError(422, OrgRefusal.IMPORT_INVALID, "a new person needs an email")
            people.provision(actor, username, email, profile, reason)
            return username, "create"
        before = people.snapshot(existing)
        people.update(actor, username, profile, reason)
        existing.refresh_from_db()
        return username, "update" if people.snapshot(existing) != before else "unchanged"

    def read(self, text: str, *, required: tuple[str, ...]) -> list[tuple[int, dict[str, str]]]:
        """The CSV's lines with their line numbers; refuses a file without the columns."""
        reader = csv.DictReader(io.StringIO(text.strip()))
        columns = {c.strip() for c in reader.fieldnames or []}
        missing = [c for c in required if c not in columns]
        if missing:
            raise OrgError(422, OrgRefusal.IMPORT_INVALID, f"missing columns: {', '.join(missing)}")
        lines = [
            (reader.line_num, {k.strip(): (v or "") for k, v in row.items() if k}) for row in reader
        ]
        limit = settings.THRESHOLDS.access.import_max_rows
        if len(lines) > limit:
            raise OrgError(
                413, OrgRefusal.IMPORT_TOO_LARGE, f"{len(lines)} rows; the limit is {limit}"
            )
        return lines

    def parents_first(
        self, lines: list[tuple[int, dict[str, str]]], codes: set[str]
    ) -> list[tuple[int, dict[str, str]]]:
        """The lines ordered so a department comes after its parent in the same file."""
        by_code = {line["code"].strip().upper(): (n, line) for n, line in lines}
        ordered: list[tuple[int, dict[str, str]]] = []
        placed: set[str] = set()

        def place(code: str, seen: frozenset[str]) -> None:
            if code in placed or code in seen:
                return
            parent = (by_code[code][1].get("parent_code") or "").strip().upper()
            if parent in codes:
                place(parent, seen | {code})
            placed.add(code)
            ordered.append(by_code[code])

        for code in by_code:
            place(code, frozenset())
        return ordered


# --- the import service ---

org_import = OrgImport()
