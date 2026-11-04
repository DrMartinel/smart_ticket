"use client";

// The Reports section's tabs and building blocks (F10): who sees each tab follows the routes' gates.

import { useEffect, useState, type ReactNode } from "react";
import { api, ApiError, download } from "@/lib/api";
import type { CurrentUser } from "@/lib/auth";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { TabNav } from "@/components/TabNav";

export type ReportTab =
  | "sla"
  | "teams"
  | "reviewers"
  | "kb"
  | "csat"
  | "rollout"
  | "security"
  | "incidents"
  | "notifications";

const has = (user: CurrentUser, cap: string) => (user.capabilities ?? []).includes(cap);
const leads = (user: CurrentUser) => (user.teams ?? []).filter((t) => t.role === "lead").map((t) => t.team);

/** The tabs `user` may open, in display order. */
export function reportTabs(user: CurrentUser): { key: ReportTab; label: string }[] {
  const manager = user.role === "manager";
  const tech = user.role === "technician";
  const tabs: { key: ReportTab; label: string; show: boolean }[] = [
    { key: "sla", label: "SLA", show: manager || leads(user).length > 0 },
    { key: "teams", label: "Teams", show: manager || (tech && (user.teams ?? []).length > 0) },
    { key: "reviewers", label: "Reviewers", show: manager || tech },
    { key: "kb", label: "KB", show: manager || has(user, "kb_editor") },
    { key: "csat", label: "CSAT", show: manager || leads(user).length > 0 },
    { key: "rollout", label: "Rollout", show: manager || user.role === "security" },
    { key: "security", label: "Security", show: manager || user.role === "security" },
    { key: "incidents", label: "Incidents", show: manager || has(user, "incident_manager") },
    { key: "notifications", label: "Notifications", show: manager || has(user, "workflow_admin") },
  ];
  return tabs.filter((t) => t.show);
}

export function ReportTabs({ user, active }: { user: CurrentUser; active: ReportTab }) {
  return (
    <TabNav
      tabs={reportTabs(user).map((t) => ({ href: `/admin/reports/${t.key}`, label: t.label, active: active === t.key }))}
    />
  );
}

/** The teams a report's team picker offers: every team for a manager, else the ones `user` leads. */
export function pickableTeams(user: CurrentUser, all: string[]): string[] {
  return user.role === "manager" ? all : leads(user);
}

export function Stat({ label, value, note, tone }: { label: string; value: string; note?: ReactNode; tone?: "warn" | "danger" }) {
  const color = tone === "danger" ? "text-danger" : tone === "warn" ? "text-warn" : "";
  return (
    <Card className="p-4">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
      {note && <p className="mt-1 text-xs text-muted-foreground">{note}</p>}
    </Card>
  );
}

export function Header({ title, note, children }: { title: string; note: string; children?: ReactNode }) {
  return (
    <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
      <div>
        <h1 className="text-xl font-semibold">{title}</h1>
        <p className="text-xs text-muted-foreground">{note}</p>
      </div>
      <div className="flex flex-wrap items-end gap-2">{children}</div>
    </header>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

/** "2026-10" for this month in Asia/Ho_Chi_Minh. */
export function thisMonth(): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Ho_Chi_Minh", year: "numeric", month: "2-digit" })
    .format(new Date())
    .slice(0, 7);
}

export function MonthPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <Field label="Month">
      <Input type="month" className="w-40" value={value} onChange={(e) => onChange(e.target.value)} />
    </Field>
  );
}

export function query(params: Record<string, string | number | null | undefined>): string {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== null && v !== undefined && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
}

export function ExportButton({ path, filename }: { path: string; filename: string }) {
  const [error, setError] = useState(false);
  const run = async () => {
    setError(false);
    try {
      const blob = await download(path);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = filename;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch {
      setError(true);
    }
  };
  return (
    <div className="flex flex-col items-end">
      <Button variant="outline" onClick={() => void run()}>
        Export CSV
      </Button>
      {error && <span className="text-xs text-danger">Couldn't export the CSV.</span>}
    </div>
  );
}

/** Loads `path` whenever it changes; the error is the server's code and message. */
export function useReport<T>(path: string | null): { data: T | null; error: string | null } {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!path) return;
    let live = true;
    setError(null);
    api
      .get<T>(path)
      .then((r) => live && setData(r))
      .catch((err) => {
        if (!live) return;
        setData(null);
        setError(err instanceof ApiError ? `${err.message}${err.code ? ` (${err.code})` : ""}` : "Couldn't load this report.");
      });
    return () => {
      live = false;
    };
  }, [path]);
  return { data, error };
}

export function Bar({ value, good }: { value: number | null; good?: boolean }) {
  const pct = value === null ? 0 : Math.max(0, Math.min(1, value)) * 100;
  return (
    <div className="h-2 w-full rounded-full bg-muted">
      <div
        className={`h-2 rounded-full ${good ? "bg-ok" : "bg-warn"}`}
        style={{ width: `${pct}%` }}
      />
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="px-4 py-6 text-center text-sm text-muted-foreground">{children}</p>;
}

export function ReportTable({ head, children }: { head: string[]; children: ReactNode }) {
  return (
    <Card className="overflow-x-auto">
      <Table className="min-w-[640px]">
        <TableHeader>
          <TableRow>
            {head.map((h, i) => (
              <TableHead key={i} className={`px-4 py-2.5 font-medium ${i > 0 ? "text-right" : ""}`}>
                {h}
              </TableHead>
            ))}
          </TableRow>
        </TableHeader>
        <TableBody className="[&_td]:px-4 [&_td]:py-2 [&_td+td]:text-right [&_td+td]:font-mono [&_td+td]:tabular-nums [&_tr]:border-t [&_tr]:border-border">
          {children}
        </TableBody>
      </Table>
    </Card>
  );
}
