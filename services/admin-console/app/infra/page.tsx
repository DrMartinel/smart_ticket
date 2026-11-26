"use client";

// The cloud's resources and firing alerts (F17 FR-F17-013), by project, each linking to its page.

import Link from "next/link";
import { Server } from "lucide-react";
import { useEffect, useState } from "react";
import { Labeled, Tabs } from "@/components/Modal";
import { SeverityBadge, StatusBadge, useProjects } from "@/components/infra/shared";
import { Card } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { relativeTime } from "@/lib/format";
import { resourceHref, type ResourceKind } from "@/lib/infra";
import { P, can } from "@/lib/permissions";
import type { AlertOut, NetworkOut, ServerOut, VolumeOut } from "@/lib/types/generated";

type Tab = "servers" | "volumes" | "networks" | "alerts";

type Listing =
  | { tab: "servers"; rows: ServerOut[] }
  | { tab: "volumes"; rows: VolumeOut[] }
  | { tab: "networks"; rows: NetworkOut[] }
  | { tab: "alerts"; rows: AlertOut[] };

const TABS: { key: Tab; label: string }[] = [
  { key: "servers", label: "Servers" },
  { key: "volumes", label: "Volumes" },
  { key: "networks", label: "Networks" },
  { key: "alerts", label: "Alerts" },
];

const ALERT_RESOURCE: [string, ResourceKind][] = [
  ["server_id", "server"],
  ["volume_id", "volume"],
  ["network_id", "network"],
];

export default function InfraPage() {
  const user = useRequireAuth();
  const reads = can(user, P.infraRead);
  const projects = useProjects(reads);
  const [tab, setTab] = useState<Tab>("servers");
  const [project, setProject] = useState("");
  const [listing, setListing] = useState<Listing | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!reads) return;
    let current = true;
    setListing(null);
    setError(null);
    const query = project ? `?project_id=${encodeURIComponent(project)}` : "";
    const read = (): Promise<Listing> => {
      switch (tab) {
        case "servers":
          return api.get<ServerOut[]>(`/api/infra/servers${query}`).then((rows) => ({ tab, rows }));
        case "volumes":
          return api.get<VolumeOut[]>(`/api/infra/volumes${query}`).then((rows) => ({ tab, rows }));
        case "networks":
          return api.get<NetworkOut[]>(`/api/infra/networks${query}`).then((rows) => ({ tab, rows }));
        case "alerts":
          return api.get<AlertOut[]>(`/api/infra/alerts${query}`).then((rows) => ({ tab, rows }));
      }
    };
    read()
      .then((found) => current && setListing(found))
      .catch((err) => {
        if (!current) return;
        if (err instanceof ApiError && err.code === "infra_backend_unavailable") {
          setError(
            tab === "alerts"
              ? "Alertmanager didn't answer, so alerts aren't shown. That is not the same as none firing."
              : "The cloud didn't answer, so this list isn't known right now.",
          );
        } else if (err instanceof ApiError && err.code === "infra_scope_unavailable") {
          setError("Keystone didn't answer, so your projects couldn't be read.");
        } else {
          setError("Couldn't load this list.");
        }
      });
    return () => {
      current = false;
    };
  }, [reads, tab, project, attempt]);

  if (!user) return null;
  if (!reads) {
    return (
      <Page>
        <PageHeader eyebrow="Workspace / Cloud" title="Cloud resources" />
        <ErrorState title="You can't read the cloud." />
      </Page>
    );
  }

  const projectName = (id: string | null) => (id ? (projects[id] ?? id) : "—");
  const shown = listing?.tab === tab ? listing : null;
  const empty = (
    <EmptyState compact icon={Server} title={tab === "alerts" ? "No alert is firing" : `No ${tab}`}>
      {project ? "Nothing in this project." : "Nothing in the projects you can reach."}
    </EmptyState>
  );

  return (
    <Page className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Workspace / Cloud"
        title="Cloud resources"
        description="What the cloud runs in the projects you can reach, and what is alerting. Open a resource for its state, metrics and the assistant's changes to it."
        actions={
          <Labeled label="Project" className="w-full sm:w-56">
            <NativeSelect value={project} onChange={(e) => setProject(e.target.value)}>
              <option value="">All projects</option>
              {Object.entries(projects).map(([id, name]) => (
                <option key={id} value={id}>
                  {name}
                </option>
              ))}
            </NativeSelect>
          </Labeled>
        }
      />
      <Tabs tabs={TABS} value={tab} onChange={setTab} />
      {error && <ErrorState title={error} onRetry={() => setAttempt((n) => n + 1)} />}
      <Card className="overflow-x-auto">
        <Table className="min-w-[760px]">
          {shown?.tab === "servers" && (
            <>
              <TableHeader>
                <TableRow>
                  <TableHead>Server</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Project</TableHead>
                  <TableHead>Flavor</TableHead>
                  <TableHead>Addresses</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.rows.map((s) => (
                  <TableRow key={s.id}>
                    <TableCell>
                      <Link href={resourceHref("server", s.id)} className="font-medium text-primary hover:underline">
                        {s.name || s.id}
                      </Link>
                      <div className="font-mono text-xs text-muted-foreground">{s.id}</div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={s.status} /> {s.task_state && <span className="text-xs text-muted-foreground">{s.task_state}</span>}
                    </TableCell>
                    <TableCell>{projectName(s.project_id)}</TableCell>
                    <TableCell>{s.flavor || "—"}</TableCell>
                    <TableCell>{s.addresses.map((a) => a.ip).join(", ") || "—"}</TableCell>
                  </TableRow>
                ))}
                <TableStatus colSpan={5} rows={shown.rows} error={!!error} empty={empty} />
              </TableBody>
            </>
          )}
          {shown?.tab === "volumes" && (
            <>
              <TableHeader>
                <TableRow>
                  <TableHead>Volume</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Project</TableHead>
                  <TableHead>Size</TableHead>
                  <TableHead>Attached to</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.rows.map((v) => (
                  <TableRow key={v.id}>
                    <TableCell>
                      <Link href={resourceHref("volume", v.id)} className="font-medium text-primary hover:underline">
                        {v.name || v.id}
                      </Link>
                      <div className="font-mono text-xs text-muted-foreground">{v.id}</div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={v.status} />
                    </TableCell>
                    <TableCell>{projectName(v.project_id)}</TableCell>
                    <TableCell>{v.size_gb} GB</TableCell>
                    <TableCell>
                      {v.attachments.length === 0
                        ? "—"
                        : v.attachments.map((a) => (
                            <Link key={a.server_id} href={resourceHref("server", a.server_id)} className="mr-2 font-mono text-xs text-primary hover:underline">
                              {a.server_id}
                            </Link>
                          ))}
                    </TableCell>
                  </TableRow>
                ))}
                <TableStatus colSpan={5} rows={shown.rows} error={!!error} empty={empty} />
              </TableBody>
            </>
          )}
          {shown?.tab === "networks" && (
            <>
              <TableHeader>
                <TableRow>
                  <TableHead>Network</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Project</TableHead>
                  <TableHead>Description</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.rows.map((n) => (
                  <TableRow key={n.id}>
                    <TableCell>
                      <Link href={resourceHref("network", n.id)} className="font-medium text-primary hover:underline">
                        {n.name || n.id}
                      </Link>
                      <div className="font-mono text-xs text-muted-foreground">{n.id}</div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={n.status} />
                    </TableCell>
                    <TableCell>{projectName(n.project_id)}</TableCell>
                    <TableCell className="max-w-[320px] truncate">{n.description || "—"}</TableCell>
                  </TableRow>
                ))}
                <TableStatus colSpan={4} rows={shown.rows} error={!!error} empty={empty} />
              </TableBody>
            </>
          )}
          {shown?.tab === "alerts" && (
            <>
              <TableHeader>
                <TableRow>
                  <TableHead>Alert</TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Resource</TableHead>
                  <TableHead>Project</TableHead>
                  <TableHead>Since</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {shown.rows.map((a) => {
                  const [label, kind] = ALERT_RESOURCE.find(([l]) => a.labels[l]) ?? [];
                  return (
                    <TableRow key={a.fingerprint}>
                      <TableCell>
                        <span className="font-medium">{a.name}</span>
                        {a.summary && <div className="text-xs text-muted-foreground">{a.summary}</div>}
                      </TableCell>
                      <TableCell>
                        <SeverityBadge severity={a.severity} />
                      </TableCell>
                      <TableCell>
                        {label && kind ? (
                          <Link href={resourceHref(kind, a.labels[label])} className="font-mono text-xs text-primary hover:underline">
                            {a.labels[label]}
                          </Link>
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell>{projectName(a.project_id)}</TableCell>
                      <TableCell>
                        {a.state} {relativeTime(a.starts_at)}
                      </TableCell>
                    </TableRow>
                  );
                })}
                <TableStatus colSpan={5} rows={shown.rows} error={!!error} empty={empty} />
              </TableBody>
            </>
          )}
          {!shown && !error && (
            <TableBody>
              <TableStatus colSpan={5} rows={null} empty={empty} />
            </TableBody>
          )}
        </Table>
      </Card>
    </Page>
  );
}
