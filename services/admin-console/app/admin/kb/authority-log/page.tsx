"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState, TableStatus } from "@/components/ui/states";


// The authority log (F6 · Authority log 13-1180): every change to a page's auto-reply authority
// or risk tier, filterable, with an audited CSV export.

import { useCallback, useEffect, useState } from "react";
import { vnTime } from "@/components/security/badges";
import { api, download } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { AuthorityLogOut } from "@/lib/types/generated";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { SectionTabs } from "@/components/TabNav";

interface Filters {
  slug: string;
  actor: string;
  field: string;
  from: string;
  to: string;
}

const EMPTY: Filters = { slug: "", actor: "", field: "", from: "", to: "" };

function query(f: Filters): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v.trim()) params.set(k, v.trim());
  return params.toString();
}

export default function AuthorityLogPage() {
  const user = useRequireAuth();
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [rows, setRows] = useState<AuthorityLogOut[] | null>(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const q = query(applied);
    api
      .get<{ items: AuthorityLogOut[]; count: number }>(`/api/kb/authority-log?limit=200${q ? `&${q}` : ""}`)
      .then((page) => {
        setRows(page.items);
        setCount(page.count);
        setError(null);
      })
      .catch(() => setError("Couldn't load the authority log."));
  }, [applied]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  if (!user) return null;

  const exportCsv = async () => {
    try {
      const q = query(applied);
      const blob = await download(`/api/kb/authority-log.csv${q ? `?${q}` : ""}`);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "kb-authority-log.csv";
      link.click();
      URL.revokeObjectURL(link.href);
    } catch {
      setError("Couldn't export the CSV. Try again.");
    }
  };

  const input = (key: keyof Filters, label: string, width: string, type = "text") => (
    <label className={`flex flex-col gap-1 ${width}`}>
      <span className="text-xs font-medium text-foreground/80">{label}</span>
      <Input type={type} value={filters[key]} onChange={(e) => setFilters({ ...filters, [key]: e.target.value })} />
    </label>
  );

  return (
    <Page className="flex flex-col gap-4">
      <SectionTabs />
      <PageHeader
        className="mb-2"
        eyebrow="Admin / Help pages"
        vi="Nhật ký quyền"
        title="Authority log"
        description={<>Every change to a page's auto-reply authority and risk tier. Exports are recorded in the audit log.</>}
      />

      <form
        className="mb-4 flex flex-wrap items-end gap-3 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(filters);
        }}
      >
        {input("slug", "Page", "w-64")}
        {input("actor", "Actor", "w-40")}
        <label className="flex w-44 flex-col gap-1">
          <span className="text-xs font-medium text-foreground/80">Field</span>
          <NativeSelect value={filters.field} onChange={(e) => setFilters({ ...filters, field: e.target.value })}>
            <option value="">all</option>
            <option value="auto_reply_allowed">auto_reply_allowed</option>
            <option value="risk_tier">risk_tier</option>
          </NativeSelect>
        </label>
        {input("from", "From", "w-40", "date")}
        {input("to", "To", "w-40", "date")}
        <Button variant="outline" type="submit">
          Apply filters
        </Button>
        <Button variant="outline" type="button" className="ml-auto" onClick={() => void exportCsv()}>
          Export CSV
        </Button>
      </form>

      {error && <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}

      <Card className="overflow-x-auto">
        <Table className="min-w-[900px]">
          <TableHeader>
            <TableRow>
              <TableHead>When</TableHead>
              <TableHead>Page</TableHead>
              <TableHead>Field</TableHead>
              <TableHead>Change</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Reason</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows?.map((r) => (
              <TableRow key={r.id} className="align-top">
                <TableCell className="whitespace-nowrap">{vnTime(r.changed_at)}</TableCell>
                <TableCell className="num text-xs">{r.slug}</TableCell>
                <TableCell>{r.field}</TableCell>
                <TableCell className="whitespace-nowrap">
                  {r.old_value ?? "—"} → {r.new_value ?? "—"}
                </TableCell>
                <TableCell>{r.actor}</TableCell>
                <TableCell>{r.reason}</TableCell>
              </TableRow>
            ))}
            <TableStatus colSpan={6} rows={rows} error={!!error} empty={<EmptyState compact title="No entries match these filters" />} />
          </TableBody>
        </Table>
      </Card>
      {rows && count > rows.length && <p className="mt-2 text-xs text-muted-foreground">Showing {rows.length} of {count}. Narrow the filters or export the CSV for the rest.</p>}
    </Page>
  );
}
