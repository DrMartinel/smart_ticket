"""The simulator's Prometheus metrics: gauges read live, counters advanced on every tick."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from prometheus_client.core import CounterMetricFamily, GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from cloud_sim.cloud import Cloud, ServerStatus
from cloud_sim.telemetry.readings import port_reading, server_reading, volume_reading

_SERVER_LABELS = ["project", "project_name", "server_id", "server", "host"]
_VOLUME_LABELS = ["project", "project_name", "volume_id", "volume", "server_id"]
_PORT_LABELS = ["project", "project_name", "port_id", "network_id", "server_id", "server"]


class Telemetry:
    """The tick count and every counter's running total."""

    def __init__(self) -> None:
        self.tick = 0
        self.totals: dict[tuple[str, str], float] = defaultdict(float)

    def advance(self, cloud: Cloud, seconds: float) -> None:
        """Adds one tick's worth of IOPS and packets to the counters."""
        with cloud.reading():
            self.tick += 1
            for volume in cloud.volumes.values():
                reading = volume_reading(cloud, volume, self.tick)
                self.totals["iops", volume.id] += reading.iops * seconds
            for server in cloud.servers.values():
                port = port_reading(cloud, server, self.tick)
                self.totals["rx", server.port_id] += port.rx_pps * seconds
                self.totals["tx", server.port_id] += port.tx_pps * seconds
                self.totals["dropped", server.port_id] += port.dropped_pps * seconds


class CloudCollector(Collector):
    """Reads the cloud each time Prometheus scrapes."""

    def __init__(self, cloud: Cloud, telemetry: Telemetry) -> None:
        self.cloud = cloud
        self.telemetry = telemetry

    def collect(self) -> Iterator[Metric]:
        cloud, tick, totals = self.cloud, self.telemetry.tick, self.telemetry.totals
        up = GaugeMetricFamily(
            "cloud_server_up", "Whether the server's guest answers.", labels=_SERVER_LABELS
        )
        status = GaugeMetricFamily(
            "cloud_server_status",
            "The server's Nova status, one series per status.",
            labels=[*_SERVER_LABELS, "status"],
        )
        cpu = GaugeMetricFamily(
            "cloud_server_cpu_utilization_ratio", "CPU in use.", labels=_SERVER_LABELS
        )
        memory = GaugeMetricFamily(
            "cloud_server_memory_used_ratio", "Memory in use.", labels=_SERVER_LABELS
        )
        disk = GaugeMetricFamily(
            "cloud_server_disk_used_ratio", "Root disk in use.", labels=_SERVER_LABELS
        )
        read = GaugeMetricFamily(
            "cloud_volume_read_latency_seconds", "Mean read latency.", labels=_VOLUME_LABELS
        )
        write = GaugeMetricFamily(
            "cloud_volume_write_latency_seconds", "Mean write latency.", labels=_VOLUME_LABELS
        )
        iops = CounterMetricFamily(
            "cloud_volume_iops", "I/O operations served.", labels=_VOLUME_LABELS
        )
        quota = GaugeMetricFamily(
            "cloud_volume_iops_quota", "The volume's IOPS limit.", labels=_VOLUME_LABELS
        )
        rx = CounterMetricFamily("cloud_port_rx_packets", "Packets received.", labels=_PORT_LABELS)
        tx = CounterMetricFamily("cloud_port_tx_packets", "Packets sent.", labels=_PORT_LABELS)
        dropped = CounterMetricFamily(
            "cloud_port_rx_dropped", "Packets dropped.", labels=_PORT_LABELS
        )

        with cloud.reading():
            for server in cloud.servers.values():
                project = cloud.projects[server.project_id]
                labels = [project.id, project.name, server.id, server.name, server.host]
                reading = server_reading(cloud, server, tick)
                up.add_metric(labels, 1.0 if reading.up else 0.0)
                shown = cloud.status_of(server)
                for s in ServerStatus:
                    status.add_metric([*labels, s.value], 1.0 if s is shown else 0.0)
                cpu.add_metric(labels, reading.cpu)
                memory.add_metric(labels, reading.memory)
                disk.add_metric(labels, reading.disk)
                port_labels = [
                    project.id,
                    project.name,
                    server.port_id,
                    cloud.network_of(server).id,
                    server.id,
                    server.name,
                ]
                rx.add_metric(port_labels, totals["rx", server.port_id])
                tx.add_metric(port_labels, totals["tx", server.port_id])
                dropped.add_metric(port_labels, totals["dropped", server.port_id])
            for volume in cloud.volumes.values():
                project = cloud.projects[volume.project_id]
                labels = [project.id, project.name, volume.id, volume.name, volume.server_id or ""]
                volume_now = volume_reading(cloud, volume, tick)
                read.add_metric(labels, volume_now.read_latency)
                write.add_metric(labels, volume_now.write_latency)
                iops.add_metric(labels, totals["iops", volume.id])
                quota.add_metric(labels, float(volume.iops_quota))
        yield from (up, status, cpu, memory, disk, read, write, iops, quota, rx, tx, dropped)
