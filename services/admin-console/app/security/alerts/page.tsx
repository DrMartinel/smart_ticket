"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";

// The security inbox (F8 · Security inbox 15-1087): most severe first, then oldest.

import Link from "next/link";
import { useEffect, useState } from "react";
import { SeverityChip, StateChip, vnTime } from "@/components/security/badges";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { AlertRowOut } from "@/lib/types/generated";
import { NativeSelect } from "@/components/ui/native-select";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

const KINDS = [
  "pii_critical",
  "credential_in_reply",
  "refresh_token_reused",
  "break_glass_sign_in",
  "break_glass_in_keycloak",
  "injection_detected",
  "ambiguous_role",
  "reveal_rate_limited",
  "decrypt_failed",
  "reveal_failed",
  "access_denied_burst",
];

export default function SecurityInboxPage() {
  const user = useRequireAuth();
  const [state, setState] = useState("open");
  const [kind, setKind] = useState("");
  const [assignee, setAssignee] = useState("");
  const [rows, setRows] = useState<AlertRowOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    const params = new URLSearchParams();
    if (state) params.set("state", state);
    if (kind) params.set("kind", kind);
    if (assignee.trim()) params.set("assignee", assignee.trim());
    api
      .get<AlertRowOut[]>(`/api/security/alerts?${params}`)
      .then((r) => {
        setRows(r);
        setError(null);
      })
      .catch(() => setError("Couldn't load the alerts."));
  }, [user, state, kind, assignee]);

  if (!user) return null;

  return (
    <Page className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Security / Alerts"
        title="Security alerts"
        description={<>Severity first, then oldest. Ack targets: critical 1 business hour, high 4, medium 1 business day (BR-F8-04).</>}
        actions={
      <>
      <div className="flex flex-wrap gap-3 text-sm">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">State</span>
          <NativeSelect value={state} onChange={(e) => setState(e.target.value)}>
            <option value="open">open</option>
            <option value="new">new</option>
            <option value="acknowledged">acknowledged</option>
            <option value="investigating">investigating</option>
            <option value="closed">closed</option>
            <option value="">all</option>
          </NativeSelect>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Kind</span>
          <NativeSelect value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">all</option>
            {KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </NativeSelect>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">Assignee</span>
          <Input className="w-32" value={assignee} placeholder="any" onChange={(e) => setAssignee(e.target.value)} />
        </label>
      </div>
      </>
      }
      />

      {error && <ErrorState title={error} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[860px]">
          <TableHeader>
            <TableRow>
              <TableHead>Severity</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>Ticket / user</TableHead>
              <TableHead>Count</TableHead>
              <TableHead>First seen</TableHead>
              <TableHead>Ack due</TableHead>
              <TableHead>State</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows?.map((a) => (
              <TableRow
                key={a.id}
                className={`border-t border-border ${a.overdue || (a.severity === "critical" && a.state === "new") ? "bg-danger-soft" : ""}`}
              >
                <TableCell>
                  <SeverityChip severity={a.severity} />
                </TableCell>
                <TableCell className="num text-xs">{a.kind}</TableCell>
                <TableCell>
                  {a.ticket ? `${a.ticket.public_id} · ${a.ticket.reporter}` : a.subject_user ? `user ${a.subject_user}` : "—"}
                </TableCell>
                <TableCell>{a.count}</TableCell>
                <TableCell>{vnTime(a.first_seen_at)}</TableCell>
                <TableCell>
                  {a.acknowledged_at ? (
                    <Badge variant="neutral" className="bg-ok-soft text-ok">acked {vnTime(a.acknowledged_at)}</Badge>
                  ) : a.overdue ? (
                    <Badge variant="neutral" className="bg-danger-soft text-danger">overdue {vnTime(a.ack_due_at)}</Badge>
                  ) : (
                    <Badge variant="neutral" className="bg-primary-soft text-primary">{vnTime(a.ack_due_at)}</Badge>
                  )}
                </TableCell>
                <TableCell>
                  <StateChip state={a.state} resolution={a.resolution} />
                </TableCell>
                <TableCell className="text-right">
                  <Link href={`/security/alerts/${a.id}`} className="text-primary hover:underline">
                    Open
                  </Link>
                </TableCell>
              </TableRow>
            ))}
            <TableStatus colSpan={8} rows={rows} error={!!error} empty={<EmptyState compact title="No alerts" />} />
          </TableBody>
        </Table>
      </Card>
      <p className="text-xs text-muted-foreground">
        Same kind + same ticket (or user) within 60 min increments one alert (BR-F8-03). Managers see only counts by kind and
        state (BR-F8-01).
      </p>
    </Page>
  );
}
