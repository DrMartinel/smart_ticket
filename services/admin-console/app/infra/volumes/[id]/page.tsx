"use client";

// One volume (F17 FR-F17-013, UC-F17-03): its state, the servers it is attached to and its alerts,
// its latency and IOPS against its quota, and the assistant's changes to it, applied here.

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
import type { VolumeOut } from "@/lib/types/generated";

export default function VolumePage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const reads = can(user, P.infraRead);
  const projects = useProjects(reads);
  const [volume, setVolume] = useState<VolumeOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<VolumeOut>(`/api/infra/volumes/${encodeURIComponent(id)}`)
      .then((v) => {
        setVolume(v);
        setError(null);
      })
      .catch((err) => setError(readError(err, "volume")));
  }, [id]);

  useEffect(() => {
    if (reads) load();
  }, [reads, load]);

  const filters = { volume_id: [id] };
  const matcher = `{volume_id="${id.replaceAll("\\", "\\\\").replaceAll('"', '\\"')}"}`;
  return (
    <ResourceFrame
      kind="Volume"
      title={volume?.name ?? ""}
      loaded={!!volume}
      error={error}
      onRetry={load}
      meta={
        volume && (
          <>
            <StatusBadge status={volume.status} />
            <span>{projects[volume.project_id] ?? volume.project_id}</span>
            <span className="font-mono text-xs">{volume.id}</span>
          </>
        )
      }
    >
      {volume && (
        <>
          <ResourceChanges kind="volume" id={volume.id} name={volume.name} onChanged={load} />
          <div className="grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)]">
            <Panel title="State" id="state">
              <Facts termWidth="130px">
                <dt className="text-muted-foreground">Status</dt>
                <dd>
                  <StatusBadge status={volume.status} />
                </dd>
                <dt className="text-muted-foreground">Project</dt>
                <dd>{projects[volume.project_id] ?? <span className="font-mono text-xs">{volume.project_id}</span>}</dd>
                <dt className="text-muted-foreground">Size</dt>
                <dd>
                  {volume.size_gb} GB · {volume.volume_type || "—"}
                </dd>
                <dt className="text-muted-foreground">Attached to</dt>
                <dd>
                  {volume.attachments.length === 0 ? (
                    "No server"
                  ) : (
                    <ul className="flex flex-col gap-0.5">
                      {volume.attachments.map((a) => (
                        <li key={a.server_id} className="flex flex-wrap gap-2">
                          <Link href={resourceHref("server", a.server_id)} className="font-mono text-xs text-primary hover:underline">
                            {a.server_id}
                          </Link>
                          <span className="text-muted-foreground">{a.device}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </dd>
                <dt className="text-muted-foreground">Created</dt>
                <dd>{dateTime(volume.created)}</dd>
                {volume.description && (
                  <>
                    <dt className="text-muted-foreground">Description</dt>
                    <dd className="whitespace-pre-wrap">{volume.description}</dd>
                  </>
                )}
                {Object.entries(volume.metadata).map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="truncate text-muted-foreground">{k}</dt>
                    <dd className="whitespace-pre-wrap">{v}</dd>
                  </div>
                ))}
              </Facts>
            </Panel>
            <ResourceAlerts
              projectId={volume.project_id}
              labels={[
                ["volume_id", volume.id],
                ["volume", volume.name],
              ]}
            />
          </div>
          <MetricsPanel
            projectId={volume.project_id}
            presets={[
              { label: "Read latency", unit: "ms", query: { metric: "cloud_volume_read_latency_seconds", filters } },
              { label: "Write latency", unit: "ms", query: { metric: "cloud_volume_write_latency_seconds", filters } },
              {
                label: "IOPS against its quota",
                unit: "percent",
                query: { promql: `rate(cloud_volume_iops_total${matcher}[5m]) / cloud_volume_iops_quota${matcher}` },
              },
            ]}
          />
        </>
      )}
    </ResourceFrame>
  );
}
