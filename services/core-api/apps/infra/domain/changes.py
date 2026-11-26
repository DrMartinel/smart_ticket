"""The changes a person may make to the cloud (F17 §h.1, BR-F17-08): what each is, the resource
it acts on, the one call that makes it, and the internal note it leaves on a ticket."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from apps.accounts.models import Language


class InfraChange(StrEnum):
    SOFT_REBOOT = "soft_reboot"
    HARD_REBOOT = "hard_reboot"
    START = "start"
    STOP = "stop"
    ATTACH_VOLUME = "attach_volume"
    DETACH_VOLUME = "detach_volume"
    ADD_SECURITY_RULE = "add_security_rule"
    REMOVE_SECURITY_RULE = "remove_security_rule"


class InfraResource(StrEnum):
    SERVER = "server"
    VOLUME = "volume"
    SECURITY_GROUP = "security_group"


class ChangeOutcome(StrEnum):
    DONE = "done"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuleSpec:
    """A security group rule as a change names it."""

    direction: str
    ethertype: str
    protocol: str | None
    port_min: int | None
    port_max: int | None
    remote_ip_prefix: str | None

    def neutron(self, group_id: str) -> dict[str, Any]:
        """The rule as Neutron's create call takes it."""
        return {
            "security_group_rule": {
                "security_group_id": group_id,
                "direction": self.direction,
                "ethertype": self.ethertype,
                "protocol": self.protocol,
                "port_range_min": self.port_min,
                "port_range_max": self.port_max,
                "remote_ip_prefix": self.remote_ip_prefix,
            }
        }

    def described(self) -> str:
        """The rule in a few words, e.g. `ingress tcp 5432 from 10.10.0.0/24`."""
        if self.port_min is None:
            ports = ""
        elif self.port_max in (None, self.port_min):
            ports = f" {self.port_min}"
        else:
            ports = f" {self.port_min}-{self.port_max}"
        source = "from" if self.direction == "ingress" else "to"
        return (
            f"{self.direction} {self.protocol or 'any'}{ports} "
            f"{source} {self.remote_ip_prefix or 'anywhere'}"
        )


@dataclass(frozen=True)
class ChangeTarget:
    """The resource a change acts on, as the cloud named it."""

    kind: InfraResource
    id: str
    name: str
    project_id: str


@dataclass(frozen=True)
class Change:
    """One change: its kind, its target, what it is done with (a server, a rule), and the one
    cloud call that makes it."""

    kind: InfraChange
    target: ChangeTarget
    method: str
    service: str
    path: str
    body: dict[str, Any] | None = None
    using: str = ""

    def details(self) -> dict[str, str]:
        """The change and its target, as a refusal and an audit row name them."""
        return {
            "change": self.kind.value,
            "target_kind": self.target.kind.value,
            "target_id": self.target.id,
        }

    def note(self, outcome: ChangeOutcome, language: Language) -> str:
        """The internal comment the change leaves on its ticket."""
        what = _WHAT[self.kind][language].format(
            name=self.target.name or self.target.id, id=self.target.id, using=self.using
        )
        return f"{what} {_OUTCOME[outcome][language]}"


_WHAT: dict[InfraChange, dict[Language, str]] = {
    InfraChange.SOFT_REBOOT: {
        Language.EN: "Soft reboot of server {name} ({id}):",
        Language.VI: "Khởi động lại mềm máy chủ {name} ({id}):",
    },
    InfraChange.HARD_REBOOT: {
        Language.EN: "Hard reboot of server {name} ({id}):",
        Language.VI: "Khởi động lại cứng máy chủ {name} ({id}):",
    },
    InfraChange.START: {
        Language.EN: "Start of server {name} ({id}):",
        Language.VI: "Bật máy chủ {name} ({id}):",
    },
    InfraChange.STOP: {
        Language.EN: "Stop of server {name} ({id}):",
        Language.VI: "Tắt máy chủ {name} ({id}):",
    },
    InfraChange.ATTACH_VOLUME: {
        Language.EN: "Attach of volume {name} ({id}) to server {using}:",
        Language.VI: "Gắn ổ đĩa {name} ({id}) vào máy chủ {using}:",
    },
    InfraChange.DETACH_VOLUME: {
        Language.EN: "Detach of volume {name} ({id}) from server {using}:",
        Language.VI: "Tháo ổ đĩa {name} ({id}) khỏi máy chủ {using}:",
    },
    InfraChange.ADD_SECURITY_RULE: {
        Language.EN: "New rule {using} in security group {name} ({id}):",
        Language.VI: "Thêm quy tắc {using} vào nhóm bảo mật {name} ({id}):",
    },
    InfraChange.REMOVE_SECURITY_RULE: {
        Language.EN: "Removal of rule {using} from security group {name} ({id}):",
        Language.VI: "Xoá quy tắc {using} khỏi nhóm bảo mật {name} ({id}):",
    },
}

_OUTCOME: dict[ChangeOutcome, dict[Language, str]] = {
    ChangeOutcome.DONE: {
        Language.EN: "the cloud accepted it.",
        Language.VI: "hệ thống cloud đã chấp nhận.",
    },
    ChangeOutcome.UNKNOWN: {
        Language.EN: (
            "the cloud's answer was lost, so it is not known whether the change was made. "
            "Check the resource before trying again."
        ),
        Language.VI: (
            "không nhận được phản hồi từ hệ thống cloud nên chưa rõ thay đổi đã được thực hiện "
            "hay chưa. Kiểm tra lại tài nguyên trước khi thử lại."
        ),
    },
}
