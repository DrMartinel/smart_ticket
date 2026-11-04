"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState, TableStatus } from "@/components/ui/states";

// The PII access log for security: who revealed which value, when and why (F5).

import { useCallback, useEffect, useState } from "react";
import { useRequireAuth } from "@/lib/auth";
import { ApiError, api, download } from "@/lib/api";
import { piiLevelTone } from "@/lib/badges";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";

interface AccessLogRow {
  id: string;
  accessed_at: string;
  actor: string;
  ticket: string;
  placeholder: string;
  level: string;
  reason_code: string;
  reason: string;
}

interface Page {
  items: AccessLogRow[];
  count: number;
}

interface Filters {
  ticket: string;
  actor: string;
  reason_code: string;
  from: string;
  to: string;
}

const REASON_CODES = ["verify_identity", "contact_requester", "security_investigation", "legal_request"];
const EMPTY: Filters = { ticket: "", actor: "", reason_code: "", from: "", to: "" };
const LIMIT = 100;

function query(filters: Filters): string {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(filters)) if (value.trim()) params.set(key, value.trim());
  return params.toString();
}

function vnTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: "Asia/Ho_Chi_Minh",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export default function AccessLogPage() {
  const user = useRequireAuth();
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (f: Filters) => {
    setError(null);
    try {
      const q = query(f);
      setPage(await api.get<Page>(`/api/pii/access-log?limit=${LIMIT}${q ? `&${q}` : ""}`));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? "Only security can read the PII access log." : "Couldn't load the access log.");
    }
  }, []);

  useEffect(() => {
    if (user) void load(applied);
  }, [user, applied, load]);

  if (!user) return null;

  const exportCsv = async () => {
    try {
      const q = query(applied);
      const blob = await download(`/api/pii/access-log.csv${q ? `?${q}` : ""}`);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "pii-access-log.csv";
      link.click();
      URL.revokeObjectURL(link.href);
    } catch {
      setError("Couldn't export the access log.");
    }
  };

  const field = (key: keyof Filters, label: string, width: string, type = "text") => (
    <label className={`flex flex-col gap-1 ${width}`}>
      <span className="text-xs font-medium text-foreground/80">{label}</span>
      <Input
        type={type}
        value={filters[key]}
        placeholder={type === "text" ? "any" : undefined}
        onChange={(e) => setFilters({ ...filters, [key]: e.target.value })}
        className="text-sm"
      />
    </label>
  );

  return (
    <Page width="record" className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Security / PII access log"
        title="PII access log"
        description={<>Append-only. Values are never stored here or exported.</>}
        actions={
      <>
      <Button variant="outline" onClick={() => void exportCsv()}>
        Export CSV
      </Button>
      </>
      }
      />

      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(filters);
        }}
      >
        {field("ticket", "Ticket", "w-[200px]")}
        {field("actor", "Actor", "w-[160px]")}
        <label className="flex w-[200px] flex-col gap-1">
          <span className="text-xs font-medium text-foreground/80">Reason code</span>
          <NativeSelect value={filters.reason_code} onChange={(e) => setFilters({ ...filters, reason_code: e.target.value })}>
            <option value="">any</option>
            {REASON_CODES.map((code) => (
              <option key={code} value={code}>
                {code}
              </option>
            ))}
          </NativeSelect>
        </label>
        {field("from", "From", "w-[150px]", "date")}
        {field("to", "To", "w-[150px]", "date")}
        <Button variant="outline" type="submit">
          Filter
        </Button>
      </form>

      {error && <ErrorState title={error} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[720px] text-xs">
          <TableHeader>
            <TableRow>
              <TableHead>Time (+07)</TableHead>
              <TableHead>Actor</TableHead>
              <TableHead>Ticket</TableHead>
              <TableHead>Placeholder</TableHead>
              <TableHead>Reason code</TableHead>
              <TableHead>Reason (masked)</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {page?.items.map((row) => (
              <TableRow key={row.id}>
                <TableCell className="whitespace-nowrap">{vnTime(row.accessed_at)}</TableCell>
                <TableCell>{row.actor}</TableCell>
                <TableCell className="num">{row.ticket}</TableCell>
                <TableCell>
                  <Badge variant={piiLevelTone(row.level)}>{row.placeholder}</Badge>
                </TableCell>
                <TableCell>{row.reason_code}</TableCell>
                <TableCell>{row.reason}</TableCell>
              </TableRow>
            ))}
            {page && page.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="px-4 py-6 text-center text-muted-foreground">
                  No reveals match these filters.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
      <p className="text-xs text-muted-foreground">
        {page ? `${Math.min(page.count, LIMIT)} of ${page.count} shown. ` : ""}Export writes pii_access_log_exported to the audit log.
      </p>
    </Page>
  );
}
