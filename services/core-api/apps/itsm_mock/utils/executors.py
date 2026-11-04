"""Runbook executors (F12, ADR-0038): Keycloak for identity actions, n8n for the rest, and a mock
used by tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any
from urllib.parse import quote, urlparse

import httpx
from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from apps.core.errors import CodedError
from apps.itsm_mock.models import ExecutionState, ExecutorKind, RunbookExecution
from infrastructure.outbound import OutboundNoAnswer, OutboundRefused, OutboundUnavailable, outbound


class RunbookRefusal(StrEnum):
    NOT_APPROVED = "not_approved"
    NOT_A_RUNBOOK_ITEM = "not_a_runbook_item"
    APPROVER_NOT_STAFF = "approver_not_staff"
    EXECUTOR_NOT_STAFF = "executor_not_staff"
    REVIEW_ITEM_NOT_FOUND = "review_item_not_found"
    UNKNOWN_RUNBOOK = "unknown_runbook"
    RUNBOOK_NOT_APPROVED = "runbook_not_approved"
    MISSING_FIELDS = "missing_fields"
    TARGET_NOT_REPORTER = "target_not_reporter"
    GROUP_NOT_ALLOWED = "group_not_allowed"
    INVALID_CONFIG = "invalid_config"
    EXECUTION_EXISTS = "execution_exists"
    EXECUTION_NOT_FOUND = "execution_not_found"
    NOT_UNKNOWN = "not_unknown"
    NOT_AWAITING = "not_awaiting"
    BAD_CALLBACK_TOKEN = "bad_callback_token"
    RUNBOOK_EXISTS = "runbook_exists"
    ALREADY_LIVE = "already_live"


class RunbookError(CodedError):
    """A runbook request core-api refuses."""


@dataclass(frozen=True)
class Outcome:
    """What an executor reports; RUNNING with `awaiting_until` waits for a callback."""

    state: ExecutionState
    external_ref: str = ""
    error: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    awaiting_until: datetime | None = None


class Executor:
    """Runs one kind of runbook."""

    kind: ExecutorKind

    def needs(self, config: dict[str, Any]) -> set[str]:
        """The payload fields a runbook with `config` cannot run without."""
        return set()

    def config_errors(self, config: dict[str, Any]) -> list[str]:
        return []

    def check_payload(self, config: dict[str, Any], payload: dict[str, Any]) -> None:
        """Raises a RunbookError when `payload` asks for something `config` doesn't allow."""

    def run(self, execution: RunbookExecution) -> Outcome:
        raise NotImplementedError


class MockExecutor(Executor):
    """Records a simulated run, as the pre-F12 mock did."""

    kind = ExecutorKind.MOCK

    def run(self, execution: RunbookExecution) -> Outcome:
        assert execution.runbook is not None
        return Outcome(
            ExecutionState.SUCCEEDED,
            result={
                "simulated": True,
                "runbook": execution.runbook.title,
                "applied_payload": execution.executed_payload,
            },
        )


# ── Keycloak ──


class KeycloakAction(StrEnum):
    SEND_PASSWORD_RESET = "send_password_reset"
    UNLOCK_ACCOUNT = "unlock_account"
    ADD_TO_GROUP = "add_to_group"


class NotSent(Exception):
    """A Keycloak call failed before any change was asked for."""


class KeycloakAdmin:
    """One runbook's calls to the Keycloak admin API, as the runbook client (OQ-25)."""

    def __init__(self, client: httpx.Client, token: str) -> None:
        self.client = client
        self.token = token

    @staticmethod
    def realm_url() -> str:
        return f"{settings.OIDC_SERVER_URL}{urlparse(settings.OIDC_ISSUER_URL).path}"

    @staticmethod
    def admin_url() -> str:
        return f"{settings.OIDC_SERVER_URL}/admin{urlparse(settings.OIDC_ISSUER_URL).path}"

    def read(self, path: str) -> Any:
        """A GET's JSON; anything else raises NotSent."""
        try:
            response = self.client.get(
                f"{self.admin_url()}{path}", headers={"Authorization": f"Bearer {self.token}"}
            )
        except httpx.HTTPError as e:
            raise NotSent(f"Keycloak read {path} failed: {type(e).__name__}") from e
        if response.status_code != 200:
            raise NotSent(f"Keycloak read {path} answered {response.status_code}")
        try:
            return response.json()
        except ValueError as e:
            raise NotSent(f"Keycloak read {path} answered non-JSON") from e

    def user_id(self, username: str) -> str:
        found = self.read(f"/users?username={quote(username)}&exact=true")
        matches = [u for u in found if isinstance(u, dict) and u.get("username") == username]
        if len(matches) != 1:
            raise NotSent(f"Keycloak has no single user {username!r}")
        return str(matches[0]["id"])

    def group_id(self, path: str) -> str:
        found = self.read(f"/group-by-path/{quote(path.lstrip('/'))}")
        if not isinstance(found, dict) or "id" not in found:
            raise NotSent(f"Keycloak has no group {path!r}")
        return str(found["id"])

    def change(self, method: str, path: str, body: Any, ref: str) -> Outcome:
        """The one call that changes something: a failure after it may have been received is
        unknown (BR-F12-06)."""
        try:
            response = self.client.request(
                method,
                f"{self.admin_url()}{path}",
                json=body,
                headers={"Authorization": f"Bearer {self.token}"},
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as e:
            return Outcome(ExecutionState.FAILED, error=f"Keycloak unreachable: {e}")
        except httpx.HTTPError as e:
            return Outcome(
                ExecutionState.UNKNOWN, external_ref=ref, error=f"no answer: {type(e).__name__}"
            )
        if 200 <= response.status_code < 300:
            return Outcome(ExecutionState.SUCCEEDED, external_ref=ref)
        message = f"Keycloak answered {response.status_code}: {response.text[:200]}"
        if response.status_code >= 500:
            return Outcome(ExecutionState.UNKNOWN, external_ref=ref, error=message)
        return Outcome(ExecutionState.FAILED, external_ref=ref, error=message)


class KeycloakExecutor(Executor):
    """Identity actions that never handle a password (BR-F12-05)."""

    kind = ExecutorKind.KEYCLOAK

    def http(self) -> httpx.Client:
        timeout = httpx.Timeout(
            settings.ITSM_EXECUTOR_TIMEOUT_SEC, connect=settings.OIDC_HTTP_CONNECT_TIMEOUT_SEC
        )
        return httpx.Client(timeout=timeout, follow_redirects=False)

    @contextmanager
    def admin(self) -> Iterator[KeycloakAdmin]:
        with self.http() as client:
            try:
                response = client.post(
                    f"{KeycloakAdmin.realm_url()}/protocol/openid-connect/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": settings.KEYCLOAK_RUNBOOK_CLIENT_ID,
                        "client_secret": settings.KEYCLOAK_RUNBOOK_CLIENT_SECRET,
                    },
                )
                token = response.json().get("access_token") if response.status_code == 200 else None
            except (httpx.HTTPError, ValueError) as e:
                raise NotSent(f"Keycloak token request failed: {type(e).__name__}") from e
            if not isinstance(token, str):
                raise NotSent(f"the runbook client was refused ({response.status_code})")
            yield KeycloakAdmin(client, token)

    def action(self, config: dict[str, Any]) -> KeycloakAction | None:
        try:
            return KeycloakAction(str(config.get("action")))
        except ValueError:
            return None

    def needs(self, config: dict[str, Any]) -> set[str]:
        if self.action(config) is KeycloakAction.ADD_TO_GROUP:
            return {"target_username", "group"}
        return {"target_username"}

    def config_errors(self, config: dict[str, Any]) -> list[str]:
        action = self.action(config)
        if action is None:
            return [f"config.action must be one of {[a.value for a in KeycloakAction]}"]
        groups = config.get("allowed_groups")
        if action is KeycloakAction.ADD_TO_GROUP and (
            not isinstance(groups, list)
            or not groups
            or not all(isinstance(g, str) for g in groups)
        ):
            return ["config.allowed_groups must list at least one group path"]
        return []

    def ungrantable_groups(self, config: dict[str, Any]) -> list[str]:
        """Allowed groups outside ITSM_GRANTABLE_GROUP_PREFIXES."""
        if self.action(config) is not KeycloakAction.ADD_TO_GROUP:
            return []
        prefixes = settings.ITSM_GRANTABLE_GROUP_PREFIXES
        return [g for g in config.get("allowed_groups", []) if not g.startswith(tuple(prefixes))]

    def check_payload(self, config: dict[str, Any], payload: dict[str, Any]) -> None:
        if self.action(config) is not KeycloakAction.ADD_TO_GROUP:
            return
        group = payload.get("group")
        if group not in config.get("allowed_groups", []) or self.ungrantable_groups(
            {**config, "allowed_groups": [group]}
        ):
            raise RunbookError(
                422, RunbookRefusal.GROUP_NOT_ALLOWED, f"group {group!r} is not on the allow-list"
            )

    def run(self, execution: RunbookExecution) -> Outcome:
        assert execution.runbook is not None
        config = execution.runbook.config
        payload = execution.executed_payload
        action = self.action(config)
        try:
            self.check_payload(config, payload)
            with self.admin() as admin:
                user = admin.user_id(str(payload["target_username"]))
                if action is KeycloakAction.SEND_PASSWORD_RESET:
                    return admin.change(
                        "PUT",
                        f"/users/{user}/execute-actions-email",
                        ["UPDATE_PASSWORD"],
                        f"keycloak user {user}: UPDATE_PASSWORD email",
                    )
                if action is KeycloakAction.UNLOCK_ACCOUNT:
                    return admin.change(
                        "DELETE",
                        f"/attack-detection/brute-force/users/{user}",
                        None,
                        f"keycloak user {user}: brute-force lock cleared",
                    )
                if action is KeycloakAction.ADD_TO_GROUP:
                    group = admin.group_id(str(payload["group"]))
                    return admin.change(
                        "PUT",
                        f"/users/{user}/groups/{group}",
                        None,
                        f"keycloak user {user}: added to {payload['group']}",
                    )
                return Outcome(ExecutionState.FAILED, error=f"unknown action {config!r}")
        except (NotSent, RunbookError) as e:
            return Outcome(ExecutionState.FAILED, error=str(e))


# ── n8n ──


class N8nExecutor(Executor):
    """Starts an n8n workflow through the lifecycle's allow-listed client and waits for its
    signed callback (BR-F12-07)."""

    kind = ExecutorKind.N8N

    def config_errors(self, config: dict[str, Any]) -> list[str]:
        url = config.get("url")
        if not isinstance(url, str):
            return ["config.url must be the n8n webhook URL"]
        try:
            outbound.check_url(url)
        except OutboundRefused as e:
            return [str(e)]
        return []

    def run(self, execution: RunbookExecution) -> Outcome:
        assert execution.runbook is not None
        body = {
            "executionId": str(execution.id),
            "ticketId": execution.ticket.public_id,
            "runbook": execution.runbook.code,
            "payload": execution.executed_payload,
            "callbackUrl": settings.LIFECYCLE_PUBLIC_BASE_URL.rstrip("/")
            + reverse("api-1.0.0:itsm_execution_callback", kwargs={"execution_id": execution.id}),
            "callbackToken": execution.callback_token(),
        }
        url = str(execution.runbook.config.get("url"))
        try:
            response = outbound.send(url, method="POST", json_body=body)
        except OutboundRefused as e:
            return Outcome(ExecutionState.FAILED, error=str(e))
        except OutboundNoAnswer as e:
            return Outcome(ExecutionState.UNKNOWN, error=f"n8n gave no answer: {e}")
        except OutboundUnavailable as e:
            return Outcome(ExecutionState.FAILED, error=f"n8n unreachable: {e}")
        if response.ok:
            wait = timedelta(seconds=settings.ITSM_EXECUTOR_TIMEOUT_SEC)
            return Outcome(
                ExecutionState.RUNNING,
                result={"status": response.status},
                awaiting_until=timezone.now() + wait,
            )
        message = f"n8n answered {response.status}: {response.text[:200]}"
        if response.status >= 500:
            return Outcome(ExecutionState.UNKNOWN, error=message)
        return Outcome(ExecutionState.FAILED, error=message)


EXECUTORS: dict[ExecutorKind, Executor] = {
    e.kind: e for e in (KeycloakExecutor(), N8nExecutor(), MockExecutor())
}
