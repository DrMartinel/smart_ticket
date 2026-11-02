"use client";

// The team queue (F2 · Team queue 9-237): unowned tickets first, then the earliest due.

import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import SlaBadge, { PriorityChip } from "@/components/SlaBadge";
import StatusChip from "@/components/StatusChip";
import TeamPicker, { useVisibleTeams } from "@/components/TeamPicker";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { StaffTicketRow } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";

interface Page {
  items: StaffTicketRow[];
  count: number;
}

const LIMIT = 100;

export default function TeamQueuePage() {
  const user = useRequireAuth();
  const router = useRouter();
  const slug = String(useParams().slug ?? "");
  const teams = useVisibleTeams(user);
  const [unassigned, setUnassigned] = useState(false);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setPage(await api.get<Page>(`/api/teams/${encodeURIComponent(slug)}/queue?limit=${LIMIT}&unassigned=${unassigned}`));
    } catch (err) {
      setPage(null);
      setError(err instanceof ApiError && err.code === "not_a_member" ? "You're not in this team." : "Couldn't load the queue.");
    }
  }, [slug, unassigned]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;

  const take = async (row: StaffTicketRow) => {
    setNotice(null);
    try {
      await api.post(`/api/tickets/${encodeURIComponent(row.public_id)}/take`, { expected_version: row.version });
      setNotice(`You have ${row.public_id}.`);
    } catch (err) {
      setNotice(
        err instanceof ApiError && err.code === "already_assigned"
          ? `Đã có người nhận · Someone took ${row.public_id} a moment ago.`
          : `Couldn't take ${row.public_id}.`,
      );
    }
    await load();
  };

  const team = teams.find((t) => t.slug === slug);

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">{team?.name ?? slug} team queue</h1>
          <p className="text-xs text-muted-foreground">
            Unassigned first, then earliest SLA due. Members take tickets; the lead assigns and reassigns.{" "}
            <Link href={`/teams/${slug}/workload`} className="text-primary hover:underline">
              Workload
            </Link>
          </p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <TeamPicker teams={teams} value={slug} onChange={(next) => router.push(`/teams/${next}`)} />
          <label className="flex items-center gap-2 pb-2 text-sm">
            <Checkbox checked={unassigned} onCheckedChange={(checked) => setUnassigned(checked === true)} />
            Unassigned only
          </label>
        </div>
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}
      {notice && <p className="text-sm text-muted-foreground">{notice}</p>}

      <Card className="overflow-x-auto">
        <Table className="w-full min-w-[820px] text-left text-sm">
          <TableHeader className="bg-background text-[11px] text-muted-foreground">
            <TableRow>
              <TableHead className="px-4 py-2 font-normal">Ticket</TableHead>
              <TableHead className="px-4 py-2 font-normal">Subject</TableHead>
              <TableHead className="px-4 py-2 font-normal">Priority</TableHead>
              <TableHead className="px-4 py-2 font-normal">Assignee</TableHead>
              <TableHead className="px-4 py-2 font-normal">Status</TableHead>
              <TableHead className="px-4 py-2 font-normal">SLA</TableHead>
              <TableHead className="px-4 py-2 font-normal" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {page?.items.map((row) => (
              <TableRow key={row.public_id} className={`border-t border-border ${row.assignee ? "" : "bg-muted"}`}>
                <TableCell className="whitespace-nowrap px-4 py-2.5 font-mono text-xs">
                  <Link href={`/tickets/${row.public_id}`} className="hover:underline">
                    {row.public_id}
                  </Link>
                </TableCell>
                <TableCell className="max-w-[360px] px-4 py-2.5">{row.subject_masked}</TableCell>
                <TableCell className="px-4 py-2.5">
                  <PriorityChip priority={row.priority} />
                </TableCell>
                <TableCell className="px-4 py-2.5">{row.assignee ?? <span className="text-muted-foreground">Unassigned</span>}</TableCell>
                <TableCell className="px-4 py-2.5">
                  <StatusChip name={row.status.name} color={row.status.color} />
                </TableCell>
                <TableCell className="whitespace-nowrap px-4 py-2.5">
                  <SlaBadge badge={row.sla} />
                </TableCell>
                <TableCell className="px-4 py-2.5 text-right">
                  {!row.assignee ? (
                    <Button onClick={() => void take(row)}>
                      Take
                    </Button>
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>
            ))}
            {page && page.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="px-4 py-6 text-center text-muted-foreground">
                  Nothing in this queue.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
