"use client";

// Mass incidents (F7 · Incident list 14-952): proposed first for the incident manager to decide.

import Link from "next/link";
import { useEffect, useState } from "react";
import { IncidentStatusChip, StageChip, eta } from "@/components/incidents/chips";
import { vnTime } from "@/components/security/badges";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { IncidentRowOut } from "@/lib/types/generated";

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
          <p className="text-xs text-[var(--text-muted)]">
            The detector only proposes; an incident manager confirms or dismisses (BR-F7-01).
          </p>
        </div>
        <div className="flex items-end gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Status</span>
            <select className="field" value={status} onChange={(e) => setStatus(e.target.value)}>
              <option value="">open + resolved</option>
              <option value="proposed">proposed</option>
              <option value="confirmed">confirmed</option>
              <option value="resolved">resolved</option>
              <option value="dismissed">dismissed</option>
              <option value="closed">closed</option>
            </select>
          </label>
          {isManager && (
            <Link href="/incidents/new" className="btn btn-primary">
              Khai báo sự cố
            </Link>
          )}
        </div>
      </header>

      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2.5 font-medium">Incident</th>
              <th className="px-4 py-2.5 font-medium">Status</th>
              <th className="px-4 py-2.5 font-medium">Stage</th>
              <th className="px-4 py-2.5 font-medium">Tickets</th>
              <th className="px-4 py-2.5 font-medium">ETA</th>
              <th className="px-4 py-2.5 font-medium">Target</th>
              <th className="px-4 py-2.5 font-medium">Opened</th>
            </tr>
          </thead>
          <tbody>
            {rows?.map((i) => (
              <tr key={i.public_id} className={`border-t border-[var(--border)] ${i.status === "proposed" ? "bg-[var(--warn-soft)]" : ""}`}>
                <td className="px-4 py-2.5">
                  <Link href={`/incidents/${i.public_id}`} className="font-medium text-[var(--accent)] hover:underline">
                    {i.public_id}
                  </Link>
                  <div className="text-xs text-[var(--text-muted)]">
                    {i.title}
                    {i.service ? ` · ${i.service}` : ""}
                  </div>
                </td>
                <td className="px-4 py-2.5">
                  <IncidentStatusChip status={i.status} />
                </td>
                <td className="px-4 py-2.5">{i.status === "proposed" ? "—" : <StageChip stage={i.stage} />}</td>
                <td className="px-4 py-2.5">{i.ticket_count}</td>
                <td className="px-4 py-2.5">{eta(i.eta, i.eta_unknown)}</td>
                <td className="px-4 py-2.5">
                  {i.target_resolve_at ? (
                    <span className={i.target_breached ? "text-[var(--danger)]" : ""}>
                      {vnTime(i.target_resolve_at)}
                      {i.target_breached ? " · breached" : ""}
                    </span>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="px-4 py-2.5">{vnTime(i.created_at)}</td>
              </tr>
            ))}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={7} className="px-4 py-6 text-center text-[var(--text-muted)]">
                  Không có sự cố.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
