"use client";

// Mass incidents (F7 · Incident list 14-952): proposed first for the incident manager to decide.

import Link from "next/link";
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

const ORDER: Record<string, number> = { proposed: 0, confirmed: 1, resolved: 2 };

export default function IncidentsPage() {
  const user = useRequireAuth();
  const [status, setStatus] = useState("");
  const [rows, setRows] = useState<IncidentRowOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const isManager = user?.capabilities?.includes("incident_manager") ?? false;

  useEffect(() => {
    if (!user) return;
    api
      .get<IncidentRowOut[]>(`/api/incidents${status ? `?status=${status}` : ""}`)
      .then((r) => {
        setRows([...r].sort((a, b) => (ORDER[a.status] ?? 9) - (ORDER[b.status] ?? 9)));
        setError(null);
      })
      .catch(() => setError("Không tải được danh sách sự cố."));
  }, [user, status]);

  if (!user) return null;

  return (
    <div className="mx-auto flex max-w-[1180px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Sự cố diện rộng · Incidents</h1>
          <p className="text-xs text-muted-foreground">
            The detector only proposes; an incident manager confirms or dismisses (BR-F7-01).
          </p>
        </div>
        <div className="flex items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Status</span>
            <NativeSelect value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">open + resolved</option>
              <option value="proposed">proposed</option>
              <option value="confirmed">confirmed</option>
              <option value="resolved">resolved</option>
              <option value="dismissed">dismissed</option>
              <option value="closed">closed</option>
            </NativeSelect>
          </label>
          {isManager && (
            <Button asChild>
              <Link href="/incidents/new">
                Khai báo sự cố
              </Link>
            </Button>
          )}
        </div>
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}

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
              <TableRow key={i.public_id} className={`${i.status === "proposed" ? "bg-warn-soft" : ""}`}>
                <TableCell>
                  <Link href={`/incidents/${i.public_id}`} className="font-medium text-primary hover:underline">
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
            {rows?.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="px-4 py-6 text-center text-muted-foreground">
                  Không có sự cố.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
