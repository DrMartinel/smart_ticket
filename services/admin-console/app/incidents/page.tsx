"use client";

// Mass incidents (F7 · Incident list 14-952): proposed first for the incident manager to decide.

import Link from "next/link";
import { Plus, Siren } from "lucide-react";
import { Labeled } from "@/components/Modal";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";
import { useEffect, useState } from "react";
import { IncidentStatusChip, StageChip, eta } from "@/components/incidents/chips";
import { vnTime } from "@/components/security/badges";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { IncidentRowOut } from "@/lib/types/generated";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { P, can } from "@/lib/permissions";

const ORDER: Record<string, number> = { proposed: 0, confirmed: 1, resolved: 2 };

export default function IncidentsPage() {
  const user = useRequireAuth();
  const [status, setStatus] = useState("");
  const [rows, setRows] = useState<IncidentRowOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isManager = can(user, P.incidentsManage);

  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    if (!user) return;
    setRows(null);
    api
      .get<IncidentRowOut[]>(`/api/incidents${status ? `?status=${status}` : ""}`)
      .then((r) => {
        setRows([...r].sort((a, b) => (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9)));
        setError(null);
      })
      .catch(() => setError("Couldn't load incidents."));
  }, [user, status, attempt]);

  if (!user) return null;

  return (
    <Page className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Workspace / Incidents"
        vi="Sự cố diện rộng"
        title="Incidents"
        description="Outages affecting many people. The detector only proposes an incident; an incident manager confirms or dismisses it."
        actions={
        <div className="flex w-full flex-wrap items-end gap-3 sm:w-auto">
          <Labeled label="Status" className="w-full sm:w-44">
            <NativeSelect value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">Open and resolved</option>
              <option value="proposed">proposed</option>
              <option value="confirmed">confirmed</option>
              <option value="resolved">resolved</option>
              <option value="dismissed">dismissed</option>
              <option value="closed">closed</option>
            </NativeSelect>
          </Labeled>
          {isManager && (
            <Button asChild>
              <Link href="/incidents/new">
                <Plus aria-hidden /> Declare incident
              </Link>
            </Button>
          )}
        </div>
        }
      />

      {error && <ErrorState title={error} onRetry={() => { setError(null); setAttempt((n) => n + 1); }} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[860px]">
          <TableHeader>
            <TableRow>
              <TableHead>Incident</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead>Tickets</TableHead>
              <TableHead>ETA</TableHead>
              <TableHead>Target</TableHead>
              <TableHead>Opened</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows?.map((i) => (
              <TableRow key={i.public_id} className={i.status === "proposed" ? "bg-proposal-soft/60" : ""}>
                <TableCell>
                  <Link href={`/incidents/${i.public_id}`} className="num font-medium text-primary hover:underline">
                    {i.public_id}
                  </Link>
                  <div className="text-xs text-muted-foreground">
                    {i.title}
                    {i.service ? ` · ${i.service}` : ""}
                  </div>
                </TableCell>
                <TableCell>
                  <IncidentStatusChip status={i.status} />
                </TableCell>
                <TableCell>{i.status === "proposed" ? "—" : <StageChip stage={i.stage} />}</TableCell>
                <TableCell>{i.ticket_count}</TableCell>
                <TableCell>{eta(i.eta, i.eta_unknown)}</TableCell>
                <TableCell>
                  {i.target_resolve_at ? (
                    <span className={i.target_breached ? "text-danger" : ""}>
                      {vnTime(i.target_resolve_at)}
                      {i.target_breached ? " · breached" : ""}
                    </span>
                  ) : (
                    "—"
                  )}
                </TableCell>
                <TableCell>{vnTime(i.created_at)}</TableCell>
              </TableRow>
            ))}
            <TableStatus
              colSpan={7}
              rows={rows}
              error={!!error}
              empty={
                <EmptyState compact icon={Siren} title={status ? `No ${status} incidents` : "No incidents"}>
                  When many similar tickets arrive at once, the detector proposes an incident here for a manager to confirm.
                </EmptyState>
              }
            />
          </TableBody>
        </Table>
      </Card>
    </Page>
  );
}
