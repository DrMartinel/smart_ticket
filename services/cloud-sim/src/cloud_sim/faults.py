"""The faults a scenario can inject into the simulated cloud, and what each one targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any


class Target(StrEnum):
    SERVER = "server"
    VOLUME = "volume"
    NETWORK = "network"
    API = "api"


class FaultKind(StrEnum):
    """A failure the simulator can show in its state, metrics, logs and traces."""

    # A volume answers slowly: read and write latency rise, IOPS fall.
    VOLUME_DEGRADED = "volume_degraded"
    # A volume runs at its IOPS quota, so requests queue.
    IOPS_THROTTLED = "iops_throttled"
    # A server's root disk is full; its workload logs write errors.
    DISK_FULL = "disk_full"
    # A server's guest stops answering. Only a hard reboot, or a stop and start, clears it.
    SERVER_HUNG = "server_hung"
    # A server's workload keeps crashing; Nova shows it in ERROR.
    CRASH_LOOP = "crash_loop"
    # A server's CPU is saturated.
    CPU_SATURATION = "cpu_saturation"
    # A network drops packets; callers across it time out.
    PACKET_LOSS = "packet_loss"
    # A server logs a line that tries to give an assistant instructions.
    LOG_INJECTION = "log_injection"
    # The cloud's API answers after `delay_sec` seconds.
    API_SLOW = "api_slow"
    # The cloud's API answers 503.
    API_UNAVAILABLE = "api_unavailable"


TARGETS: dict[FaultKind, Target] = {
    FaultKind.VOLUME_DEGRADED: Target.VOLUME,
    FaultKind.IOPS_THROTTLED: Target.VOLUME,
    FaultKind.DISK_FULL: Target.SERVER,
    FaultKind.SERVER_HUNG: Target.SERVER,
    FaultKind.CRASH_LOOP: Target.SERVER,
    FaultKind.CPU_SATURATION: Target.SERVER,
    FaultKind.PACKET_LOSS: Target.NETWORK,
    FaultKind.LOG_INJECTION: Target.SERVER,
    FaultKind.API_SLOW: Target.API,
    FaultKind.API_UNAVAILABLE: Target.API,
}


@dataclass(frozen=True)
class Fault:
    """One injected fault, on one resource or on the API."""

    id: str
    kind: FaultKind
    target_id: str | None
    started_at: datetime
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def target(self) -> Target:
        """The kind of thing this fault is on."""
        return TARGETS[self.kind]
