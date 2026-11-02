"use client";

// SLA at risk and breached (F1 · Breach list 8-685): warned and breached clocks, earliest due first.

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import SlaBadge, { PriorityChip } from "@/components/SlaBadge";
import { useVisibleTeams } from "@/components/TeamPicker";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { BreachOut } from "@/lib/types/generated";
import { NativeSelect } from "@/components/ui/native-select";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface Page {
  items: BreachOut[];
  count: number;
}

const LIMIT = 200;

function vnTime(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: "Asia/Ho_Chi_Minh",
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export default function SlaAtRiskPage() {
  const user = useRequireAuth();
  const teams = useVisibleTeams(user);
  const [team, setTeam] = useState("");
  const [level, setLevel] = useState("");
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const params = new URLSearchParams({ limit: String(LIMIT) });
    if (team) params.set("team", team);
    if (level) params.set("state", level);
    try {
      setPage(await api.get<Page>(`/api/sla/breaches?${params}`));
      setError(null);
    } catch {
      setError("Couldn't load the SLA list.");
    }
  }, [team, level]);

  useEffect(() => {
    if (!user) return;
    void load();
    const timer = setInterval(() => void load(), 60_000);
    return () => clearInterval(timer);
  }, [user, load]);

  if (!user) return null;

  const breached = page?.items.filter((r) => r.breached_at).length ?? 0;

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">SLA at risk and breached</h1>
          <p className="text-xs text-muted-foreground">Clocks at 75 % of their target or more, earliest due first. Updated every minute.</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex w-[180px] flex-col gap-1">
            <span className="text-[11px] text-muted-foreground">Team</span>
            <NativeSelect value={team} onChange={(e) => setTeam(e.target.value)}>
              <option value="">All</option>
              {teams.map((t) => (
                <option key={t.slug} value={t.slug}>
                  {t.name}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label className="flex w-[140px] flex-col gap-1">
            <span className="text-[11px] text-muted-foreground">Level</span>
            <NativeSelect value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="">All</option>
              <option value="warned">At risk</option>
              <option value="breached">Breached</option>
            </NativeSelect>
          </label>
        </div>
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}

      <Card className="overflow-x-auto">
        <Table className="w-full min-w-[900px] text-left text-sm">
          <TableHeader className="bg-background text-[11px] text-muted-foreground">
            <TableRow>
              <TableHead className="px-4 py-2 font-normal">Ticket</TableHead>
              <TableHead className="px-4 py-2 font-normal">Subject</TableHead>
              <TableHead className="px-4 py-2 font-normal">Priority</TableHead>
              <TableHead className="px-4 py-2 font-normal">Assignee</TableHead>
              <TableHead className="px-4 py-2 font-normal">Clock</TableHead>
              <TableHead className="px-4 py-2 font-normal">Due (+07)</TableHead>
              <TableHead className="px-4 py-2 font-normal">SLA</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {page?.items.map((r) => (
              <TableRow key={`${r.ticket}-${r.kind}`} className="border-t border-border">
                <TableCell className="whitespace-nowrap px-4 py-2.5 font-mono text-xs">
                  <Link href={`/tickets/${r.ticket}`} className="hover:underline">
                    {r.ticket}
                  </Link>
                </TableCell>
                <TableCell className="max-w-[340px] px-4 py-2.5">{r.subject}</TableCell>
                <TableCell className="px-4 py-2.5">
                  <PriorityChip priority={r.priority} />
                </TableCell>
                <TableCell className="px-4 py-2.5">{r.assignee ?? "—"}</TableCell>
                <TableCell className="px-4 py-2.5">{r.kind}</TableCell>
                <TableCell className="whitespace-nowrap px-4 py-2.5">{vnTime(r.due_at)}</TableCell>
                <TableCell className="whitespace-nowrap px-4 py-2.5">
                  <SlaBadge badge={r.sla} />
                </TableCell>
              </TableRow>
            ))}
            {page && page.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="px-4 py-6 text-center text-muted-foreground">
                  Nothing at risk.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
      <p className="text-[11px] text-muted-foreground">
        {page ? `${breached} breached · ${page.items.length - breached} at risk. ` : ""}Priority never rises by itself on a breach.
      </p>
    </div>
  );
}
