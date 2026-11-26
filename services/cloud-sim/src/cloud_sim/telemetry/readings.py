"""What each resource reads at a given tick: CPU, disk, latency, IOPS and packet rates, faults included."""

from __future__ import annotations

import zlib
from dataclasses import dataclass

from cloud_sim.cloud import Cloud, Server, Volume, VolumeStatus
from cloud_sim.faults import FaultKind

# A workload's usual CPU share and the IOPS its data volume sees.
_CPU = {"postgres": 0.35, "orders-api": 0.25, "nginx": 0.15, "redis": 0.10}
_IOPS = {"postgres": 1800.0, "orders-api": 300.0, "nginx": 150.0, "redis": 50.0}
# A healthy volume's latency in seconds, and how much a fault multiplies it.
_READ_LATENCY, _WRITE_LATENCY = 0.004, 0.006
_LATENCY_FACTOR = {FaultKind.VOLUME_DEGRADED: 25.0, FaultKind.IOPS_THROTTLED: 8.0}
# Packets per second on a healthy port, and the share a lossy network drops.
_RX_PPS, _TX_PPS, _LOSS_RATIO = 800.0, 750.0, 0.08


def noise(key: str, tick: int) -> float:
    """A repeatable value in [-1, 1] for this key at this tick."""
    return (zlib.crc32(f"{key}:{tick}".encode()) % 2001) / 1000.0 - 1.0


@dataclass(frozen=True)
class ServerReading:
    up: bool
    cpu: float
    memory: float
    disk: float


@dataclass(frozen=True)
class VolumeReading:
    read_latency: float
    write_latency: float
    iops: float


@dataclass(frozen=True)
class PortReading:
    rx_pps: float
    tx_pps: float
    dropped_pps: float


def server_reading(cloud: Cloud, server: Server, tick: int) -> ServerReading:
    """The server's readings: a stopped one reads zero, a hung one spins."""
    up = cloud.is_up(server)
    hung = cloud.has_fault(FaultKind.SERVER_HUNG, server.id)
    running = up or hung
    cpu = _CPU.get(server.workload, 0.2) + 0.05 * noise(server.id + "cpu", tick)
    if hung or cloud.has_fault(FaultKind.CPU_SATURATION, server.id):
        cpu = 0.97 + 0.02 * noise(server.id + "cpu", tick)
    disk = 0.42 + 0.01 * noise(server.id + "disk", tick)
    if cloud.has_fault(FaultKind.DISK_FULL, server.id):
        disk = 0.995
    return ServerReading(
        up=up,
        cpu=max(0.0, cpu) if running else 0.0,
        memory=0.55 + 0.03 * noise(server.id + "mem", tick) if running else 0.0,
        disk=disk,
    )


def latency_factor(cloud: Cloud, volume: Volume) -> float:
    """How many times slower than healthy the volume answers."""
    factors = [f for kind, f in _LATENCY_FACTOR.items() if cloud.has_fault(kind, volume.id)]
    return max(factors, default=1.0)


def volume_reading(cloud: Cloud, volume: Volume, tick: int) -> VolumeReading:
    """The volume's readings: a volume with no running server does nothing."""
    server = cloud.servers.get(volume.server_id) if volume.server_id else None
    if server is None or volume.status is not VolumeStatus.IN_USE or not cloud.is_up(server):
        return VolumeReading(0.0, 0.0, 0.0)
    factor = latency_factor(cloud, volume)
    wobble = 1.0 + 0.15 * noise(volume.id + "lat", tick)
    iops = _IOPS.get(server.workload, 100.0) * (1.0 + 0.1 * noise(volume.id + "iops", tick))
    if cloud.has_fault(FaultKind.IOPS_THROTTLED, volume.id):
        iops = float(volume.iops_quota)
    elif cloud.has_fault(FaultKind.VOLUME_DEGRADED, volume.id):
        iops *= 0.3
    return VolumeReading(
        read_latency=_READ_LATENCY * factor * wobble,
        write_latency=_WRITE_LATENCY * factor * wobble,
        iops=min(iops, float(volume.iops_quota)),
    )


def port_reading(cloud: Cloud, server: Server, tick: int) -> PortReading:
    """The server's port readings: a lossy network drops a share of what arrives."""
    if not cloud.is_up(server):
        return PortReading(0.0, 0.0, 0.0)
    rx = _RX_PPS * (1.0 + 0.1 * noise(server.port_id + "rx", tick))
    tx = _TX_PPS * (1.0 + 0.1 * noise(server.port_id + "tx", tick))
    fault = cloud.fault_on(FaultKind.PACKET_LOSS, cloud.network_of(server).id)
    ratio = float(fault.params.get("ratio", _LOSS_RATIO)) if fault else 0.0
    return PortReading(rx, tx, rx * ratio)
