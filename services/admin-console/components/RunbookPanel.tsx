"use client";

import { ErrorState, LoadingState } from "@/components/ui/states";

// A runbook proposal on its review item (F12 UC-F12-01, 02): the payload the approver edits, the
// execution and the verdict on an unknown outcome.

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { RunbookExecutionOut, RunbookPanelOut } from "@/lib/types/generated";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";

const STATE_VI: Record<string, { label: string; tone: Tone }> = {
  queued: { label: "Queued", tone: "info" },
  running: { label: "Running", tone: "info" },
  succeeded: { label: "Succeeded", tone: "ok" },
  failed: { label: "Failed", tone: "danger" },
  unknown: { label: "Outcome unknown", tone: "warn" },
};

const REFUSAL_VI: Record<string, string> = {
  target_not_reporter: "This runbook can only target the requester themselves.",
  missing_fields: "A required field is missing.",
  group_not_allowed: "That group isn't on the list of groups that can be granted.",
  runbook_not_approved: "This runbook isn't enabled in the catalog.",
  not_approved: "The proposal hasn't been approved yet.",
  execution_exists: "This proposal already has a run that hasn't failed.",
};

function message(err: unknown): string {
  if (!(err instanceof ApiError)) return "That didn't go through. Try again.";
  return (err.code && REFUSAL_VI[err.code]) || `${err.code ?? err.status}: ${err.message}`;
}

function Execution({
  execution,
  busy,
  onResolve,
}: {
  execution: RunbookExecutionOut;
  busy: boolean;
  onResolve: (state: "succeeded" | "failed", note: string) => void;
}) {
  const [note, setNote] = useState("");
  const state = STATE_VI[execution.state] ?? { label: execution.state, tone: "" };
  return (
    <li className="rounded-md border border-border p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <Badge variant={state.tone}>{state.label}</Badge>
        <span className="text-xs text-muted-foreground">
          Attempt {execution.attempt} · {dateTime(execution.executed_at)}
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-[140px_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted-foreground">Data it ran with</dt>
        <dd className="font-mono">{JSON.stringify(execution.executed_payload)}</dd>
        <dt className="text-muted-foreground">Approved by</dt>
        <dd>
          {execution.approved_by ?? "—"} · run by {execution.executed_by}
          {execution.second_approver && ` · second approver: ${execution.second_approver}`}
        </dd>
        {execution.external_ref && (
          <>
            <dt className="text-muted-foreground">Reference</dt>
            <dd className="font-mono">{execution.external_ref}</dd>
          </>
        )}
        {execution.error && (
          <>
            <dt className="text-muted-foreground">Error</dt>
            <dd className="text-danger">{execution.error}</dd>
          </>
        )}
        {execution.resolved_by && (
          <>
            <dt className="text-muted-foreground">Confirmation</dt>
            <dd>
              {execution.resolved_by}: “{execution.resolution_note}”
            </dd>
          </>
        )}
      </dl>
      {execution.state === "unknown" && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <Input
            className="min-w-[240px] flex-1"
            placeholder="What you checked on the target system (required)" aria-label="Confirmation note"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <Button variant="outline" disabled={busy || !note.trim()} onClick={() => onResolve("succeeded", note)}>
            It succeeded
          </Button>
          <Button variant="outline" disabled={busy || !note.trim()} onClick={() => onResolve("failed", note)}>
            It failed
          </Button>
        </div>
      )}
    </li>
  );
}

export default function RunbookPanel({
  itemId,
  onChanged,
}: {
  itemId: string;
  onChanged: () => void;
}) {
  const [panel, setPanel] = useState<RunbookPanelOut | null>(null);
  const [payload, setPayload] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .get<RunbookPanelOut>(`/api/itsm/review-items/${itemId}/runbook`)
      .then((p) => {
        setPanel(p);
        const fields = new Set([...(p.runbook?.required_fields ?? []), ...Object.keys(p.draft_payload)]);
        setPayload(Object.fromEntries([...fields].map((f) => [f, String(p.draft_payload[f] ?? "")])));
      })
      .catch((err) => setError(message(err)));
  }, [itemId]);

  useEffect(load, [load]);

  const run = async (call: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await call();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
      load();
      onChanged();
    }
  };

  if (!panel) return error ? <ErrorState compact title={error} /> : <LoadingState rows={2} label="Loading runbook" />;
  const runbook = panel.runbook;
  const open = panel.executions.some((e) => e.state !== "failed");

  return (
    <div className="mt-4 flex flex-col gap-3 border-t border-border pt-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">Runbook · {panel.runbook_id ?? "—"}</span>
        {runbook && (
          <>
            <span className="text-muted-foreground">{runbook.title}</span>
            <Badge variant={runbook.risk === "high" ? "danger" : "info"}>
              {runbook.risk === "high" ? "High risk" : "Low risk"}
            </Badge>
            {runbook.target_rule === "reporter" && <Badge variant="neutral">Requester only</Badge>}
            <Badge variant="neutral">{runbook.executor}</Badge>
          </>
        )}
      </div>
      {runbook && !runbook.runnable && (
        <Alert variant="warn" className="text-xs"><AlertDescription>This runbook isn't enabled in the catalog yet, so it can't run.</AlertDescription></Alert>
      )}
      {!open && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => api.post(`/api/itsm/review-items/${itemId}/execute`, { payload }));
          }}
        >
          <p className="text-xs text-muted-foreground">
            The AI proposed this data. Check and correct it before running: what runs is exactly what you see here.
          </p>
          {Object.keys(payload).map((field) => (
            <label key={field} className="grid grid-cols-[160px_1fr] items-center gap-2 text-sm">
              <span className="font-mono text-xs">{field}</span>
              <Input
                className="font-mono"
                value={payload[field]}
                onChange={(e) => setPayload({ ...payload, [field]: e.target.value })}
              />
            </label>
          ))}
          <div>
            <Button type="submit" disabled={busy || !panel.approved || !runbook?.runnable}>
              Run runbook
            </Button>
            {!panel.approved && <span className="ml-3 text-xs text-muted-foreground">Approve the proposal first.</span>}
          </div>
        </form>
      )}
      {error && <Alert variant="danger" className="text-sm"><AlertDescription>{error}</AlertDescription></Alert>}
      {panel.executions.length > 0 && (
        <ul className="flex flex-col gap-2">
          {panel.executions.map((e) => (
            <Execution
              key={e.id}
              execution={e}
              busy={busy}
              onResolve={(state, note) => void run(() => api.post(`/api/itsm/executions/${e.id}/resolve`, { state, note }))}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
