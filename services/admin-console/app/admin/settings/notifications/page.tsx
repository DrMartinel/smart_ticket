"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";

// The notification matrix (F4 · 11-710): who gets each event on which channel by default.

import { useEffect, useMemo, useState } from "react";
import Switch from "@/components/Switch";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { MatrixCellOut, MatrixChangeIn, MatrixIn, RecipientKind } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { SectionTabs } from "@/components/TabNav";
import { P, can } from "@/lib/permissions";

type Channel = "in_app" | "email";

interface Row {
  key: string;
  event: string;
  label: string;
  owner: string;
  active: boolean;
  kind: RecipientKind;
  cells: Partial<Record<Channel, MatrixCellOut>>;
}

const cellKey = (event: string, kind: string, channel: string) => `${event}|${kind}|${channel}`;

function rows(cells: MatrixCellOut[]): Row[] {
  const byRow = new Map<string, Row>();
  for (const c of cells) {
    const key = `${c.event}|${c.recipient_kind}`;
    const row = byRow.get(key) ?? {
      key,
      event: c.event,
      label: c.label,
      owner: c.owner,
      active: c.active,
      kind: c.recipient_kind as RecipientKind,
      cells: {},
    };
    row.cells[c.channel as Channel] = c;
    byRow.set(key, row);
  }
  return [...byRow.values()];
}

function refusal(err: unknown): string {
  if (!(err instanceof ApiError)) return "Couldn't save the matrix.";
  switch (err.code) {
    case "reason_required":
      return "Say why the defaults change.";
    case "mandatory_cell":
      return "A mandatory notice can't be turned off.";
    case "unknown_event":
      return "That event isn't in the catalog.";
    default:
      return err.status === 403 ? "Only a workflow admin can change the matrix." : err.message;
  }
}

export default function NotificationMatrixPage() {
  const user = useRequireAuth();
  const [cells, setCells] = useState<MatrixCellOut[] | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [showInactive, setShowInactive] = useState(false);
  const canEdit = can(user, P.notificationsMatrixManage);

  useEffect(() => {
    if (!user) return;
    api
      .get<MatrixCellOut[]>("/api/notifications/matrix")
      .then(setCells)
      .catch((err) => setError(err instanceof ApiError && err.status === 403 ? "Only managers and workflow admins can see the matrix." : "Couldn't load the matrix."));
  }, [user]);

  const all = useMemo(() => (cells ? rows(cells) : []), [cells]);
  const shown = all.filter((r) => r.active || showInactive);
  const inactive = all.filter((r) => !r.active).length;
  const changes = Object.keys(pending).length;

  if (!user) return null;

  const valueOf = (c: MatrixCellOut) => pending[cellKey(c.event, c.recipient_kind, c.channel)] ?? c.default_on;

  const flip = (c: MatrixCellOut, next: boolean) => {
    setSaved(false);
    const key = cellKey(c.event, c.recipient_kind, c.channel);
    setPending((p) => {
      const copy = { ...p };
      if (next === c.default_on) delete copy[key];
      else copy[key] = next;
      return copy;
    });
  };

  const save = async () => {
    setError(null);
    const body: MatrixIn = {
      reason,
      changes: Object.entries(pending).map(([key, default_on]): MatrixChangeIn => {
        const [event, recipient_kind, channel] = key.split("|");
        return { event, recipient_kind: recipient_kind as RecipientKind, channel: channel as Channel, default_on };
      }),
    };
    try {
      setCells(await api.put<MatrixCellOut[]>("/api/notifications/matrix", body));
      setPending({});
      setReason("");
      setSaved(true);
    } catch (err) {
      setError(refusal(err));
    }
  };

  const cell = (row: Row, channel: Channel) => {
    const c = row.cells[channel];
    if (!c) return <span className="text-muted-foreground">—</span>;
    return (
      <Switch
        checked={valueOf(c)}
        disabled={!canEdit || c.mandatory}
        label={`${row.event} to ${row.kind} by ${channel === "in_app" ? "in-app" : "email"}`}
        onChange={(next) => flip(c, next)}
      />
    );
  };

  return (
    <Page width="record" className="flex flex-col gap-4">
      <SectionTabs className="mb-1" />
      <PageHeader
        className="mb-2"
        eyebrow="Admin / Notifications"
        title="Notification matrix"
        description={<>Defaults for who gets each event on which channel. Events and recipient kinds are code; defaults are data.</>}
        actions={
      <>
      {canEdit && (
        <Button disabled={changes === 0} onClick={() => void save()}>
          Save {changes > 0 ? `${changes} change${changes > 1 ? "s" : ""}` : "changes"}…
        </Button>
      )}
      </>
      }
      />

      {!canEdit && cells && <p className="text-xs text-muted-foreground">Read-only: only a workflow admin changes defaults.</p>}
      {error && <ErrorState title={error} />}
      {saved && <p className="text-sm text-ok">Saved. The change is in the audit log.</p>}

      <Card className="overflow-x-auto">
        <Table className="min-w-[720px] text-xs">
          <TableHeader>
            <TableRow>
              <TableHead>Event</TableHead>
              <TableHead>Recipient</TableHead>
              <TableHead>In-app</TableHead>
              <TableHead>Email</TableHead>
              <TableHead>Mandatory</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStatus colSpan={5} rows={cells ? shown : null} error={!!error} empty={<EmptyState compact title="No events in the catalog" />} />
            {shown.map((row) => (
              <TableRow key={row.key} className={`${row.active ? "" : "text-muted-foreground"}`}>
                <TableCell>
                  <span className="font-mono">{row.event}</span>
                  {!row.active && <Badge variant="neutral" className="ml-2">ships with {row.owner}</Badge>}
                </TableCell>
                <TableCell>{row.kind.replaceAll("_", " ")}</TableCell>
                <TableCell>{cell(row, "in_app")}</TableCell>
                <TableCell>{cell(row, "email")}</TableCell>
                <TableCell className="text-muted-foreground">
                  {(["in_app", "email"] as const).filter((c) => row.cells[c]?.mandatory).length === 2
                    ? "🔒 mandatory"
                    : row.cells.in_app?.mandatory
                      ? "🔒 in-app"
                      : row.cells.email?.mandatory
                        ? "🔒 email"
                        : "—"}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>
      {inactive > 0 && (
        <Button variant="link" size="inline" className="self-start text-xs" onClick={() => setShowInactive((s) => !s)}>
          {showInactive ? "Hide" : "Show"} {inactive} rows for events of features not built yet
        </Button>
      )}

      {canEdit && (
        <Card className="flex flex-col gap-2 p-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs font-medium text-foreground/80">Reason (required when saving)</span>
            <Input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} className="max-w-[640px]" placeholder="Why the defaults change" />
          </label>
          <p className="text-xs text-muted-foreground">Saving writes notif_matrix_changed to the audit log. Mandatory cells are read-only.</p>
        </Card>
      )}
    </Page>
  );
}
