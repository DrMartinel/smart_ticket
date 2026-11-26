"use client";

// One network (F17 FR-F17-013): its state, subnets, ports and its project's security groups, its
// alerts, and the packets its ports drop.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import MetricsPanel from "@/components/infra/MetricsPanel";
import { ResourceAlerts, ResourceFrame, StatusBadge, readError, useProjects } from "@/components/infra/shared";
import { Card } from "@/components/ui/card";
import { Facts, Panel } from "@/components/ui/panel";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { resourceHref } from "@/lib/infra";
import { P, can } from "@/lib/permissions";
import type { NetworkDetailOut } from "@/lib/types/generated";

export default function NetworkPage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const reads = can(user, P.infraRead);
  const projects = useProjects(reads);
  const [network, setNetwork] = useState<NetworkDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<NetworkDetailOut>(`/api/infra/networks/${encodeURIComponent(id)}`)
      .then((n) => {
        setNetwork(n);
        setError(null);
      })
      .catch((err) => setError(readError(err, "network")));
  }, [id]);

  useEffect(() => {
    if (reads) load();
  }, [reads, load]);

  const groups = Object.fromEntries((network?.security_groups ?? []).map((g) => [g.id, g.name]));
  return (
    <ResourceFrame
      kind="Network"
      title={network?.name || id}
      loaded={!!network}
      error={error}
      onRetry={load}
      meta={
        network && (
          <>
            <StatusBadge status={network.status} />
            <span>{projects[network.project_id] ?? network.project_id}</span>
            <span className="font-mono text-xs">{network.id}</span>
          </>
        )
      }
    >
      {network && (
        <>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <Panel title="State" id="state">
              <Facts termWidth="130px">
                <dt className="text-muted-foreground">Status</dt>
                <dd>
                  <StatusBadge status={network.status} />
                </dd>
                <dt className="text-muted-foreground">Project</dt>
                <dd>{projects[network.project_id] ?? <span className="font-mono text-xs">{network.project_id}</span>}</dd>
                <dt className="text-muted-foreground">Subnets</dt>
                <dd>{network.subnets.length ? network.subnets.map((s) => `${s.name || s.id} ${s.cidr}`).join(", ") : "—"}</dd>
                <dt className="text-muted-foreground">Security groups</dt>
                <dd className="flex flex-wrap gap-x-3">
                  {network.security_groups.length === 0
                    ? "—"
                    : network.security_groups.map((g) => (
                        <Link key={g.id} href={resourceHref("security_group", g.id)} className="text-primary hover:underline">
                          {g.name || g.id}
                        </Link>
                      ))}
                </dd>
                {network.description && (
                  <>
                    <dt className="text-muted-foreground">Description</dt>
                    <dd className="whitespace-pre-wrap">{network.description}</dd>
                  </>
                )}
              </Facts>
            </Panel>
            <ResourceAlerts projectId={network.project_id} labels={[["network_id", network.id]]} />
          </div>
          <Card className="overflow-x-auto">
            <Table className="min-w-[640px]">
              <TableHeader>
                <TableRow>
                  <TableHead>Port</TableHead>
                  <TableHead>Server</TableHead>
                  <TableHead>Addresses</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Security groups</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {network.ports.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={5} className="text-muted-foreground">
                      No port on this network.
                    </TableCell>
                  </TableRow>
                )}
                {network.ports.map((p) => (
                  <TableRow key={p.id}>
                    <TableCell className="font-mono text-xs">{p.id}</TableCell>
                    <TableCell>
                      {p.device_id ? (
                        <Link href={resourceHref("server", p.device_id)} className="font-mono text-xs text-primary hover:underline">
                          {p.device_id}
                        </Link>
                      ) : (
                        "—"
                      )}
                    </TableCell>
                    <TableCell>{p.ips.join(", ") || "—"}</TableCell>
                    <TableCell>
                      <StatusBadge status={p.status} />
                    </TableCell>
                    <TableCell>
                      <span className="flex flex-wrap gap-x-2">
                        {p.security_group_ids.map((g) => (
                          <Link key={g} href={resourceHref("security_group", g)} className="text-primary hover:underline">
                            {groups[g] ?? g}
                          </Link>
                        ))}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </Card>
          <MetricsPanel
            projectId={network.project_id}
            presets={[
              {
                label: "Dropped packets per port",
                unit: "per_second",
                query: { metric: "cloud_port_rx_dropped_total", function: "rate", function_seconds: 300, filters: { network_id: [network.id] } },
              },
            ]}
          />
        </>
      )}
    </ResourceFrame>
  );
}
