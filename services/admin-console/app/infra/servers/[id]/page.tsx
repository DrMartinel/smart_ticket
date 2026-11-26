"use client";

// One server (F17 FR-F17-013, UC-F17-02, UC-F17-03): its state, volumes and alerts, its metrics,
// and the assistant's changes to it, confirmed or applied here.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import MetricsPanel from "@/components/infra/MetricsPanel";
import ResourceChanges from "@/components/infra/ResourceChanges";
import { ResourceAlerts, ResourceFrame, StatusBadge, readError, useProjects } from "@/components/infra/shared";
import { Facts, Panel } from "@/components/ui/panel";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";
import { resourceHref } from "@/lib/infra";
import { P, can } from "@/lib/permissions";
import type { ServerDetailOut } from "@/lib/types/generated";

export default function ServerPage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const reads = can(user, P.infraRead);
  const projects = useProjects(reads);
  const [server, setServer] = useState<ServerDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<ServerDetailOut>(`/api/infra/servers/${encodeURIComponent(id)}`)
      .then((s) => {
        setServer(s);
        setError(null);
      })
      .catch((err) => setError(readError(err, "server")));
  }, [id]);

  useEffect(() => {
    if (reads) load();
  }, [reads, load]);

  const filters = { server_id: [id] };
  return (
    <ResourceFrame
      kind="Server"
      title={server?.name ?? ""}
      loaded={!!server}
      error={error}
      onRetry={load}
      meta={
        server && (
          <>
            <StatusBadge status={server.status} />
            {server.task_state && <span>{server.task_state}</span>}
            <span>{projects[server.project_id] ?? server.project_id}</span>
            <span className="font-mono text-xs">{server.id}</span>
          </>
        )
      }
    >
      {server && (
        <>
          <ResourceChanges kind="server" id={server.id} name={server.name} onChanged={load} />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <Panel title="State" id="state">
              <Facts termWidth="130px">
                <dt className="text-muted-foreground">Status</dt>
                <dd>
                  <StatusBadge status={server.status} /> {server.task_state && <span className="text-muted-foreground">{server.task_state}</span>}
                </dd>
                <dt className="text-muted-foreground">Project</dt>
                <dd>{projects[server.project_id] ?? <span className="font-mono text-xs">{server.project_id}</span>}</dd>
                <dt className="text-muted-foreground">Flavor</dt>
                <dd>
                  {server.flavor || "—"} · {server.vcpus} vCPU · {server.ram_mb} MB
                </dd>
                <dt className="text-muted-foreground">Host</dt>
                <dd className="font-mono text-xs">{server.host || "—"}</dd>
                <dt className="text-muted-foreground">Addresses</dt>
                <dd>{server.addresses.length ? server.addresses.map((a) => `${a.ip} (${a.network})`).join(", ") : "—"}</dd>
                <dt className="text-muted-foreground">Security groups</dt>
                <dd>{server.security_groups.join(", ") || "—"}</dd>
                <dt className="text-muted-foreground">Changed</dt>
                <dd>{dateTime(server.updated)}</dd>
                <dt className="text-muted-foreground">Created</dt>
                <dd>{dateTime(server.created)}</dd>
                {server.description && (
                  <>
                    <dt className="text-muted-foreground">Description</dt>
                    <dd className="whitespace-pre-wrap">{server.description}</dd>
                  </>
                )}
                {Object.entries(server.metadata).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="truncate text-muted-foreground">{k}</dt>
                    <dd className="whitespace-pre-wrap">{v}</dd>
                  </div>
                ))}
              </Facts>
            </Panel>
            <div className="flex min-w-0 flex-col gap-4">
              <Panel title="Volumes">
                {server.attachments.length === 0 ? (
                  <p className="text-sm text-muted-foreground">No volume is attached.</p>
                ) : (
                  <ul className="flex flex-col gap-1 text-sm">
                    {server.attachments.map((a) => (
                      <li key={a.volume_id} className="flex flex-wrap gap-2">
                        <Link href={resourceHref("volume", a.volume_id)} className="font-mono text-xs text-primary hover:underline">
                          {a.volume_id}
                        </Link>
                        <span className="text-muted-foreground">{a.device}</span>
                      </li>
                    ))}
                  </ul>
                )}
              </Panel>
              <ResourceAlerts
                projectId={server.project_id}
                labels={[
                  ["server_id", server.id],
                  ["server", server.name],
                ]}
              />
            </div>
          </div>
          <MetricsPanel
            projectId={server.project_id}
            presets={[
              { label: "CPU", unit: "percent", query: { metric: "cloud_server_cpu_utilization_ratio", filters } },
              { label: "Memory", unit: "percent", query: { metric: "cloud_server_memory_used_ratio", filters } },
              { label: "Root disk", unit: "percent", query: { metric: "cloud_server_disk_used_ratio", filters } },
            ]}
          />
        </>
      )}
    </ResourceFrame>
  );
}
