"""Threshold change requests: a full proposed thresholds.yaml, validated with the boot model,
approved by the manager who submits it, then shipped by PR (BR-F9-05, 06, ADR-0043)."""

from __future__ import annotations

import difflib
import hashlib
import uuid
from typing import Any

import yaml
from django.conf import settings
from django.db import IntegrityError, transaction
from django.utils import timezone
from pydantic import ValidationError

from apps.accounts.models import User, UserRole
from apps.audit.models import AuditLog
from apps.rollout.models import ThresholdChangeRequest
from apps.rollout.utils.rollout import file_sha256
from apps.rollout.utils.vocabulary import ChangeState, RolloutError, RolloutRefusal


def sha256_of(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ThresholdChanges:
    """Proposes, reviews and records threshold changes."""

    def current_text(self) -> str:
        with open(settings.THRESHOLDS_PATH, encoding="utf-8") as f:
            return f.read()

    def validate(self, text: str) -> dict[str, Any]:
        """Parses `text` with the model core-api boots with; 422 names the first bad field path."""
        from config.settings.base import Thresholds

        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise RolloutError(
                422, RolloutRefusal.INVALID_THRESHOLDS, f"not YAML: {e}", details={"path": ""}
            ) from e
        if not isinstance(data, dict):
            raise RolloutError(
                422, RolloutRefusal.INVALID_THRESHOLDS, "not a mapping", details={"path": ""}
            )
        try:
            Thresholds(**data)
        except ValidationError as e:
            first = e.errors()[0]
            path = ".".join(str(part) for part in first["loc"])
            raise RolloutError(
                422,
                RolloutRefusal.INVALID_THRESHOLDS,
                f"{path}: {first['msg']}",
                details={"path": path, "errors": len(e.errors())},
            ) from e
        return data

    def next_version(self) -> str:
        year = timezone.now().year
        numbers = [
            int(v.rsplit("-", 1)[1])
            for v in ThresholdChangeRequest.objects.filter(
                version__startswith=f"CR-{year}-"
            ).values_list("version", flat=True)
            if v.rsplit("-", 1)[1].isdigit()
        ]
        return f"CR-{year}-{max(numbers, default=0) + 1:03d}"

    def create(self, actor: User, text: str, evidence: str) -> ThresholdChangeRequest:
        """A draft holding the whole file; its `version` must be the request's id, so the file
        that ships is the file that was approved (ADR-0035 §4)."""
        data = self.validate(text)
        current = self.current_text()
        for _ in range(3):
            version = self.next_version()
            if str(data.get("version")) != version:
                raise RolloutError(
                    422,
                    RolloutRefusal.VERSION_MISMATCH,
                    f'set version: "{version}" in the file',
                    details={"version": version},
                )
            try:
                with transaction.atomic():
                    request = ThresholdChangeRequest.objects.create(
                        version=version,
                        yaml_text=text,
                        sha256=sha256_of(text),
                        base_sha256=file_sha256(),
                        diff="".join(
                            difflib.unified_diff(
                                current.splitlines(keepends=True),
                                text.splitlines(keepends=True),
                                fromfile="loaded",
                                tofile=version,
                            )
                        ),
                        evidence=evidence.strip(),
                        author=actor,
                    )
                    self.audit("threshold_cr_created", request, actor)
                    return request
            except IntegrityError:
                continue
        raise RolloutError(409, RolloutRefusal.VERSION_MISMATCH, "the version was taken; retry")

    def next_id(self) -> str:
        """The id a new request would get, for the author to put in the file."""
        return self.next_version()

    def locked(self, request_id: uuid.UUID) -> ThresholdChangeRequest:
        request = ThresholdChangeRequest.objects.select_for_update().filter(pk=request_id).first()
        if request is None:
            raise RolloutError(404, RolloutRefusal.NOT_FOUND, "no such change request")
        return request

    def submit(self, request_id: uuid.UUID, actor: User) -> ThresholdChangeRequest:
        """Its author, a manager, approves the draft (ADR-0043)."""
        with transaction.atomic():
            request = self.locked(request_id)
            if request.author_id != actor.id:
                raise RolloutError(403, RolloutRefusal.NOT_THE_AUTHOR, "only its author submits it")
            if actor.role != UserRole.MANAGER.value:
                raise RolloutError(403, RolloutRefusal.NOT_A_MANAGER, "only a manager approves it")
            if request.state != ChangeState.DRAFT.value:
                raise RolloutError(409, RolloutRefusal.NOT_PENDING, f"it is {request.state}")
            now = timezone.now()
            request.state = ChangeState.APPROVED.value
            request.submitted_at = now
            request.approved_at = now
            request.approvals = [
                {"user": actor.username, "role": actor.role, "at": now.isoformat(), "comment": ""}
            ]
            request.save(update_fields=["state", "submitted_at", "approved_at", "approvals"])
            self.audit("threshold_cr_approved", request, actor)
        return request

    def reject(self, request_id: uuid.UUID, actor: User, comment: str) -> ThresholdChangeRequest:
        if not comment.strip():
            raise RolloutError(422, RolloutRefusal.REASON_REQUIRED, "say why")
        with transaction.atomic():
            request = self.locked(request_id)
            if request.state != ChangeState.DRAFT.value:
                raise RolloutError(409, RolloutRefusal.NOT_PENDING, f"it is {request.state}")
            request.state = ChangeState.REJECTED.value
            request.rejected_reason = comment.strip()
            request.save(update_fields=["state", "rejected_reason"])
            self.audit("threshold_cr_rejected", request, actor)
        return request

    def audit(self, event: str, request: ThresholdChangeRequest, actor: User) -> None:
        AuditLog.objects.record(
            event,
            actor_type="human",
            actor_id=actor.id,
            payload={"version": request.version, "sha256": request.sha256},
        )


# --- the threshold changes service ---

threshold_changes = ThresholdChanges()
