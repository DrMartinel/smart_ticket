"use client";

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
    <div className="mx-auto flex max-w-[900px] flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold">Security alerts · last {summary?.days ?? 30} days</h1>
        <p className="text-xs text-muted-foreground">Counts only: the alerts themselves are for security (BR-F8-01).</p>
      </header>
      {error && <p className="text-sm text-danger">{error}</p>}
      <Card className="overflow-x-auto">
        <Table className="w-full text-left text-sm">
          <TableHeader className="text-[11px] uppercase tracking-wider text-muted-foreground">
            <TableRow>
              <TableHead className="px-4 py-2.5 font-medium">Kind</TableHead>
              {STATES.map((s) => (
                <TableHead key={s} className="px-4 py-2.5 text-right font-medium">
                  {s}
                </TableHead>
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {kinds.map((k) => (
              <TableRow key={k} className="border-t border-border">
                <TableCell className="px-4 py-2.5 font-mono text-xs">{k}</TableCell>
                {STATES.map((s) => (
                  <TableCell key={s} className="px-4 py-2.5 text-right">
                    {count(k, s)}
                  </TableCell>
                ))}
              </TableRow>
            ))}
            {summary && kinds.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                  No alerts in the window.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
