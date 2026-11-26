"use client";

// Pieces every cloud resource page shares: its frame, a status badge, project names, the
// resource's firing alerts, and what a failed read tells the person.

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { relativeTime } from "@/lib/format";
import { resourceHref } from "@/lib/infra";
import { P, can } from "@/lib/permissions";
import type { AlertOut, AlertResource, ProjectOut } from "@/lib/types/generated";
import { Badge, type Tone } from "@/components/ui/badge";
import { Page, PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";

const STATUS_TONE: Record<string, Tone> = {
  ACTIVE: "ok",
  available: "ok",
  "in-use": "ok",
  SHUTOFF: "neutral",
  ERROR: "danger",
  error: "danger",
  DOWN: "danger",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge variant={STATUS_TONE[status] ?? "info"}>{status || "unknown"}</Badge>;
}

/** What a failed read of the cloud tells the person, never "nothing found". */
export function readError(err: unknown, what: string): string {
  if (err instanceof ApiError) {
    if (err.status === 404) return `No such ${what}, or one you can't reach.`;
    if (err.status === 403) return "You can't read the cloud.";
    if (err.code === "infra_backend_unavailable") return `The cloud didn't answer, so this ${what}'s state isn't known right now.`;
  }
  return `Couldn't load this ${what}.`;
}

/** The cloud's project names by id, read once `enabled`; empty until read, or when the read fails. */
export function useProjects(enabled: boolean): Record<string, string> {
  const [names, setNames] = useState<Record<string, string>>({});
  useEffect(() => {
    if (!enabled) return;
    api
      .get<ProjectOut[]>("/api/infra/projects")
      .then((found) => setNames(Object.fromEntries(found.map((p) => [p.id, p.name]))))
      .catch(() => undefined);
  }, [enabled]);
  return names;
}

/** A resource page's frame: who may see it, its header, and its loading and failed states. */
export function ResourceFrame({
  kind,
  title,
  meta,
  error,
  loaded,
  onRetry,
  children,
}: {
  kind: string;
  title: string;
  meta?: ReactNode;
  error: string | null;
  loaded: boolean;
  onRetry: () => void;
  children: ReactNode;
}) {
  const user = useRequireAuth();
  if (!user) return null;
  const back = { href: "/infra", label: "Cloud resources" };
  if (!can(user, P.infraRead)) {
    return (
      <Page width="record">
        <PageHeader eyebrow="Workspace / Cloud" title={kind} back={back} />
        <ErrorState title="You can't read the cloud." />
      </Page>
    );
  }
  return (
    <Page width="record" className="flex flex-col gap-4">
      <PageHeader className="mb-2" eyebrow={`Workspace / Cloud / ${kind}`} title={loaded ? title : kind} meta={loaded ? meta : undefined} back={back} />
      {error ? <ErrorState title={error} onRetry={onRetry} /> : loaded ? children : <LoadingState rows={5} label={`Loading the ${kind.toLowerCase()}`} />}
    </Page>
  );
}

const SEVERITY_TONE: Record<string, Tone> = { critical: "danger", warning: "warn" };

export function SeverityBadge({ severity }: { severity: string }) {
  return <Badge variant={SEVERITY_TONE[severity] ?? "neutral"}>{severity || "alert"}</Badge>;
}

/** The alerts whose id labels name one resource, each linking its own resource when that is
 * something else, such as the server's volume. */
export function ResourceAlerts({ projectId, kind, id }: { projectId: string; kind: AlertResource; id: string }) {
  const [alerts, setAlerts] = useState<AlertOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const query = new URLSearchParams({ resource_kind: kind, resource_id: id });
    if (projectId) query.set("project_id", projectId);
    api
      .get<AlertOut[]>(`/api/infra/alerts?${query}`)
      .then(setAlerts)
      .catch((err) =>
        setError(
          err instanceof ApiError && err.code === "infra_backend_unavailable"
            ? "Alertmanager didn't answer, so alerts aren't shown. That is not the same as none firing."
            : "Couldn't load the alerts.",
        ),
      );
  }, [projectId, kind, id]);

  return (
    <Panel title="Alerts">
      {error ? (
        <ErrorState compact title={error} />
      ) : alerts === null ? (
        <LoadingState rows={2} label="Loading alerts" />
      ) : alerts.length === 0 ? (
        <EmptyState compact title={`No alert names this ${kind}`}>
          Alertmanager answered, and none of its alerts carries this {kind}&apos;s id.
        </EmptyState>
      ) : (
        <ul className="flex flex-col gap-2 text-sm">
          {alerts.map((a) => (
            <li key={a.fingerprint} className="flex flex-col gap-0.5">
              <span className="flex flex-wrap items-center gap-2">
                <SeverityBadge severity={a.severity} />
                <span className="font-medium">{a.name}</span>
                <span className="text-xs text-muted-foreground">
                  {a.state} since {relativeTime(a.starts_at)}
                </span>
                {a.resource_kind && a.resource_id && (a.resource_kind !== kind || a.resource_id !== id) && (
                  <Link href={resourceHref(a.resource_kind, a.resource_id)} className="text-xs text-primary hover:underline">
                    on {a.resource_kind} <span className="font-mono">{a.resource_id}</span>
                  </Link>
                )}
              </span>
              {a.summary && <span className="text-muted-foreground">{a.summary}</span>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
