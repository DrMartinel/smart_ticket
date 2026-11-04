"use client";

import { AlarmClockCheck } from "lucide-react";
import { Labeled } from "@/components/Modal";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";

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
    <Page className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Workspace / SLA"
        title="SLA at risk and breached"
        description="Clocks at 75% of their target or more, earliest due first. Refreshes every minute."
        actions={
        <div className="flex w-full flex-wrap items-end gap-3 sm:w-auto">
          <Labeled label="Team" className="w-full sm:w-[180px]">
            <NativeSelect value={team} onChange={(e) => setTeam(e.target.value)}>
              <option value="">All</option>
              {teams.map((t) => (
                <option key={t.slug} value={t.slug}>
                  {t.name}
                </option>
              ))}
            </NativeSelect>
          </Labeled>
          <Labeled label="Level" className="w-full sm:w-[140px]">
            <NativeSelect value={level} onChange={(e) => setLevel(e.target.value)}>
              <option value="">All</option>
              <option value="warned">At risk</option>
              <option value="breached">Breached</option>
            </NativeSelect>
          </Labeled>
        </div>
        }
      />

      {error && <ErrorState title={error} onRetry={() => void load()} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[900px]">
          <TableHeader>
            <TableRow>
              <TableHead>Ticket</TableHead>
              <TableHead>Subject</TableHead>
              <TableHead>Priority</TableHead>
              <TableHead>Assignee</TableHead>
              <TableHead>Clock</TableHead>
              <TableHead>Due (+07)</TableHead>
              <TableHead>SLA</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {page?.items.map((r) => (
              <TableRow key={`${r.ticket}-${r.kind}`}>
                <TableCell className="num whitespace-nowrap text-xs">
                  <Link href={`/tickets/${r.ticket}`} className="hover:underline">
                    {r.ticket}
                  </Link>
                </TableCell>
                <TableCell className="max-w-[340px]">{r.subject}</TableCell>
                <TableCell>
                  <PriorityChip priority={r.priority} />
                </TableCell>
                <TableCell>{r.assignee ?? "—"}</TableCell>
                <TableCell>{r.kind}</TableCell>
                <TableCell className="num whitespace-nowrap text-xs">{vnTime(r.due_at)}</TableCell>
                <TableCell className="whitespace-nowrap">
                  <SlaBadge badge={r.sla} />
                </TableCell>
              </TableRow>
            ))}
            <TableStatus
              colSpan={7}
              rows={page?.items}
              error={!!error}
              empty={
                <EmptyState compact icon={AlarmClockCheck} title="Nothing at risk">
                  {team || level ? "No clocks match these filters." : "Every running clock is under 75% of its target."}
                </EmptyState>
              }
            />
          </TableBody>
        </Table>
      </Card>
      <p className="text-xs text-muted-foreground">
        {page ? `${breached} breached · ${page.items.length - breached} at risk. ` : ""}A breach never raises a ticket&apos;s priority by itself.
      </p>
    </Page>
  );
}
