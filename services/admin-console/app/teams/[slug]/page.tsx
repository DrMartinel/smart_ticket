"use client";

import { Inbox } from "lucide-react";
import { TabNav } from "@/components/TabNav";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";

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
  const toast = useToast();

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
    try {
      await api.post(`/api/tickets/${encodeURIComponent(row.public_id)}/take`, { expected_version: row.version });
      toast.success(`${row.public_id} is yours.`, { label: "Open", onClick: () => router.push(`/tickets/${row.public_id}`) });
    } catch (err) {
      toast.error(
        err instanceof ApiError && err.code === "already_assigned"
          ? `Someone took ${row.public_id} a moment ago.`
          : `Couldn't take ${row.public_id}. Try again.`,
      );
    }
    await load();
  };

  const team = teams.find((t) => t.slug === slug);

  return (
    <Page className="flex flex-col gap-4">
      <PageHeader
        className="mb-0"
        eyebrow="Workspace / Teams"
        title={`${team?.name ?? slug} queue`}
        description="Unassigned first, then earliest SLA due. Members take tickets; the lead assigns and reassigns."
        actions={
          <div className="flex w-full flex-wrap items-end gap-3 sm:w-auto">
            <TeamPicker teams={teams} value={slug} onChange={(next) => router.push(`/teams/${next}`)} />
            <label className="flex min-h-9 items-center gap-2 text-sm">
              <Checkbox checked={unassigned} onCheckedChange={(checked) => setUnassigned(checked === true)} />
              Unassigned only
            </label>
          </div>
        }
      />
      <TabNav
        className="mb-1"
        tabs={[
          { href: `/teams/${slug}`, label: "Queue", active: true },
          { href: `/teams/${slug}/workload`, label: "Workload", active: false },
        ]}
      />

      {error && <ErrorState title={error} onRetry={error.startsWith("Couldn't") ? () => void load() : undefined} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[820px]">
          <TableHeader>
            <TableRow>
              <TableHead>Ticket</TableHead>
              <TableHead>Subject</TableHead>
              <TableHead>Priority</TableHead>
              <TableHead>Assignee</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>SLA</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {page?.items.map((row) => (
              <TableRow key={row.public_id}>
                <TableCell className="num whitespace-nowrap text-xs">
                  <Link href={`/tickets/${row.public_id}`} className="hover:underline">
                    {row.public_id}
                  </Link>
                </TableCell>
                <TableCell className="max-w-[360px]">{row.subject_masked}</TableCell>
                <TableCell>
                  <PriorityChip priority={row.priority} />
                </TableCell>
                <TableCell>{row.assignee ?? <span className="text-muted-foreground">Unassigned</span>}</TableCell>
                <TableCell>
                  <StatusChip name={row.status.name} color={row.status.color} />
                </TableCell>
                <TableCell className="whitespace-nowrap">
                  <SlaBadge badge={row.sla} />
                </TableCell>
                <TableCell className="text-right">
                  {!row.assignee ? (
                    <Button size="sm" onClick={() => void take(row)} aria-label={`Take ${row.public_id}`}>
                      Take
                    </Button>
                  ) : (
                    <span className="text-muted-foreground">—</span>
                  )}
                </TableCell>
              </TableRow>
            ))}
            <TableStatus
              colSpan={7}
              rows={page?.items}
              error={!!error}
              empty={
                <EmptyState compact icon={Inbox} title={unassigned ? "No unassigned tickets" : "This queue is empty"}>
                  {unassigned ? "Every open ticket in this team has an owner." : "New tickets in this team's categories land here."}
                </EmptyState>
              }
            />
          </TableBody>
        </Table>
      </Card>
    </Page>
  );
}
