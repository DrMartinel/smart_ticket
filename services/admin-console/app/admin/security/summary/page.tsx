"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState } from "@/components/ui/states";


// Security alert counts for managers (F8 BR-F8-01, FR-F8-009): kinds and states, no tickets or people.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { SummaryOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const STATES = ["new", "acknowledged", "investigating", "closed"];

export default function SecuritySummaryPage() {
  const user = useRequireAuth();
  const [summary, setSummary] = useState<SummaryOut | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (user) api.get<SummaryOut>("/api/security/summary").then(setSummary).catch(() => setError("Couldn't load the summary."));
  }, [user]);

  if (!user) return null;
  const kinds = [...new Set(summary?.cells.map((c) => c.kind) ?? [])].sort();
  const count = (kind: string, state: string) => summary?.cells.find((c) => c.kind === kind && c.state === state)?.count ?? 0;

  return (
    <Page className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Admin / Insights"
        title={<>Security alerts · last {summary?.days ?? 30} days</>}
        description={<>Counts only: the alerts themselves are for security (BR-F8-01).</>}
      />
      {error && <ErrorState title={error} />}
      <Card className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Kind</TableHead>
              {STATES.map((s) => (
                <TableHead key={s} className="px-4 py-2.5 text-right font-medium">
                  {s}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {kinds.map((k) => (
              <TableRow key={k}>
                <TableCell className="num text-xs">{k}</TableCell>
                {STATES.map((s) => (
                  <TableCell key={s} className="px-4 py-2.5 text-right">
                    {count(k, s)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
            {summary && kinds.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="p-0">
                  <EmptyState compact title="No alerts in the window" />
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </Page>
  );
}
