"use client";

// A ticket's cues (F17 §o, FR-F17-021): each run's outcome in words, each cue's summary, status and
// query link, and a control to link a resource, whose cues run as the person's own read (UC-F17-13).

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type {
  CueOut,
  CueRunOut,
  CueStatus,
  ResourceKind,
  TicketCuesOut,
  TicketResourceOut,
} from "@/lib/types/generated";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ErrorState, LoadingState } from "@/components/ui/states";

const STATUS: Record<CueStatus, { label: string; tone: Tone }> = {
  ok: { label: "Found", tone: "info" },
  empty: { label: "Nothing found", tone: "neutral" },
  refused: { label: "Refused", tone: "warn" },
  unavailable: { label: "Unavailable", tone: "danger" },
};

const KINDS: ResourceKind[] = ["server", "volume", "network"];

const REFUSAL: Record<string, string> = {
  infra_not_found: "The cloud has no such resource.",
  infra_backend_unavailable: "The cloud did not answer. Try again.",
};

type Linkable = { kind: ResourceKind; resource_id: string; resource: string };

function time(iso: string | null): string {
  return iso ? new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : "?";
}

function outcomeText(run: CueRunOut, customer: string | null): string {
  switch (run.outcome) {
    case "running":
      return "Collecting cues…";
    case "done":
      return run.started_by ? `Linked by ${run.started_by}` : "Collected at handoff";
    case "overview":
      return `No resource named in this ticket. What stood out in ${customer ? `${customer}'s` : "the requester's"} projects, ${time(run.window_start)}–${time(run.window_end)}`;
    case "no_cloud_user":
      return "The requester has no cloud account, so no resource was looked for.";
    case "scope_unavailable":
      return "Keystone did not answer, so no resource was linked.";
    case "failed":
      return "Collecting these cues failed; nothing here is a sign of health.";
  }
}

function sourceText(resource: TicketResourceOut): string {
  switch (resource.source) {
    case "named":
      return `named in the ticket as "${resource.token}"`;
    case "attached":
      return "attached to a server the ticket names";
    case "every_server":
      return "one of the requester's few servers";
    case "picked":
      return "picked by the requester in the chat";
    case "linked":
      return "linked from this page";
  }
}

/** The resources an overview cue's rows name with an ID, which a person may link. */
function linkables(cue: CueOut): Linkable[] {
  return Object.values(cue.evidence)
    .flatMap((rows) => (Array.isArray(rows) ? rows : []))
    .filter(
      (row): row is Linkable =>
        typeof row === "object" && row !== null && typeof row.resource_id === "string" && KINDS.includes(row.kind),
    );
}

function Cue({ cue, busy, onLink }: { cue: CueOut; busy: boolean; onLink?: (target: Linkable) => void }) {
  const status = STATUS[cue.status];
  const targets = onLink ? linkables(cue) : [];
  return (
    <li className="flex flex-col gap-1 py-1.5 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <span className="min-w-0 flex-1">{cue.summary}</span>
        <span className="flex shrink-0 items-center gap-2">
          <Badge variant={status.tone}>{status.label}</Badge>
          {cue.link && (
            <a href={cue.link} target="_blank" rel="noreferrer" className="text-xs text-primary hover:underline">
              Open query
            </a>
          )}
        </span>
      </div>
      {targets.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {targets.map((t) => (
            <Button key={t.resource_id} variant="outline" size="xs" disabled={busy} onClick={() => onLink?.(t)}>
              Link {t.resource}
            </Button>
          ))}
        </div>
      )}
    </li>
  );
}

function Run({ run, customer, busy, onLink }: { run: CueRunOut; customer: string | null; busy: boolean; onLink: (t: Linkable) => void }) {
  return (
    <li className="rounded-md border border-border p-3">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm font-medium">{outcomeText(run, customer)}</p>
        <span className="text-xs text-muted-foreground">{dateTime(run.started_at)}</span>
      </div>
      {run.overview.length > 0 && (
        <ul className="mt-2 divide-y divide-border">
          {run.overview.map((cue) => (
            <Cue key={cue.template} cue={cue} busy={busy} onLink={onLink} />
          ))}
        </ul>
      )}
      {run.resources.map((resource) => (
        <div key={resource.resource_id} className="mt-3">
          <p className="text-sm">
            <span className="font-medium">{resource.name}</span>
            <span className="text-muted-foreground">
              {" "}
              · {resource.kind}, {sourceText(resource)}
            </span>
          </p>
          <ul className="mt-1 divide-y divide-border">
            {resource.cues.map((cue) => (
              <Cue key={cue.template} cue={cue} busy={busy} />
            ))}
          </ul>
        </div>
      ))}
    </li>
  );
}

export default function CuesPanel({ publicId, customer }: { publicId: string; customer: string | null }) {
  const [runs, setRuns] = useState<CueRunOut[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [refusal, setRefusal] = useState<string | null>(null);
  const [kind, setKind] = useState<ResourceKind>("server");
  const [resourceId, setResourceId] = useState("");

  const load = useCallback(async () => {
    try {
      setRuns((await api.get<TicketCuesOut>(`/api/tickets/${publicId}/cues`)).runs);
      setFailed(false);
    } catch {
      setFailed(true);
    }
  }, [publicId]);

  useEffect(() => {
    void load();
  }, [load]);

  const link = async (target: { kind: ResourceKind; resource_id: string }) => {
    setBusy(true);
    setRefusal(null);
    try {
      await api.post(`/api/tickets/${publicId}/cues/resources`, target);
      setResourceId("");
      await load();
    } catch (err) {
      setRefusal(
        err instanceof ApiError ? (err.code && REFUSAL[err.code]) || `${err.code ?? err.status}: ${err.message}` : "That didn't go through. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (failed) return <ErrorState compact title="The cues didn't load" onRetry={() => void load()} />;
  if (runs === null) return <LoadingState rows={2} label="Loading cues" />;

  return (
    <div className="flex flex-col gap-3">
      {runs.length === 0 ? (
        <p className="text-sm text-muted-foreground">No cues for this ticket yet. They are collected when it is handed off.</p>
      ) : (
        <ul className="flex flex-col gap-3">
          {runs.map((run) => (
            <Run key={run.id} run={run} customer={customer} busy={busy} onLink={(t) => void link(t)} />
          ))}
        </ul>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {runs.some((r) => r.outcome === "running") && (
          <Button variant="outline" size="sm" disabled={busy} onClick={() => void load()}>
            Refresh
          </Button>
        )}
        <NativeSelect aria-label="Resource kind" value={kind} onChange={(e) => setKind(e.target.value as ResourceKind)}>
          {KINDS.map((k) => (
            <option key={k} value={k}>
              {k}
            </option>
          ))}
        </NativeSelect>
        <Input
          aria-label="Resource ID"
          placeholder="Resource ID"
          className="w-64"
          value={resourceId}
          onChange={(e) => setResourceId(e.target.value)}
        />
        <Button size="sm" disabled={busy || !resourceId.trim()} onClick={() => void link({ kind, resource_id: resourceId.trim() })}>
          Link a resource
        </Button>
      </div>
      {refusal && (
        <Alert variant="danger">
          <AlertDescription>{refusal}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
