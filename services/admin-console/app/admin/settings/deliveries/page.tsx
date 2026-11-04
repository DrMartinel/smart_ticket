"use client";

// The delivery log (F4 · 11-890): email and webhook messages, failures to retry.

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { deliveryStateTone, deliveryStateLabel } from "@/lib/badges";
import type { DeliveryOut, RetryOut } from "@/lib/types/generated";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { SectionTabs } from "@/components/TabNav";

interface Page {
  items: DeliveryOut[];
  count: number;
}

const LIMIT = 100;
const CHANNELS = ["", "email", "webhook", "in_app"];
const STATES = ["", "failed", "queued", "sending", "delivered"];

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

export default function DeliveryLogPage() {
  const user = useRequireAuth();
  const [channel, setChannel] = useState("");
  const [state, setState] = useState("failed");
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    const params = new URLSearchParams({ limit: String(LIMIT) });
    if (channel) params.set("channel", channel);
    if (state) params.set("state", state);
    try {
      setPage(await api.get<Page>(`/api/notifications/deliveries?${params}`));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? "Only managers and workflow admins can see deliveries." : "Couldn't load deliveries.");
    }
  }, [channel, state]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;

  const retry = async (body: { ids?: string[]; all_failed?: boolean }) => {
    setError(null);
    try {
      const { requeued } = await api.post<RetryOut>("/api/notifications/deliveries/retry", body);
      setNotice(`${requeued} message${requeued === 1 ? "" : "s"} queued again.`);
      await load();
    } catch {
      setError("Couldn't retry.");
    }
  };

  const select = (label: string, value: string, options: string[], onChange: (v: string) => void) => (
    <label className="flex w-[140px] flex-col gap-1">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <NativeSelect value={value} onChange={(e) => onChange(e.target.value)}>
        {options.map((o) => (
          <option key={o} value={o}>
            {o || "All"}
          </option>
        ))}
      </NativeSelect>
    </label>
  );

  const failed = page?.items.some((d) => d.state === "failed") ?? false;

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <SectionTabs className="mb-1" />
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Delivery log</h1>
          <p className="text-xs text-muted-foreground">Email and webhook messages. A failed send never changes the ticket.</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          {select("Channel", channel, CHANNELS, setChannel)}
          {select("State", state, STATES, setState)}
          {state === "failed" && failed && (
            <Button variant="outline" onClick={() => void retry({ all_failed: true })}>
              Retry all failed
            </Button>
          )}
        </div>
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}
      {notice && <p className="text-sm text-ok">{notice}</p>}

      <Card className="overflow-x-auto">
        <Table className="min-w-[900px] text-xs">
          <TableHeader>
            <TableRow>
              <TableHead>Created (+07)</TableHead>
              <TableHead>Event</TableHead>
              <TableHead>Recipient</TableHead>
              <TableHead>Channel</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Attempts</TableHead>
              <TableHead>Error</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {page?.items.map((d) => (
              <TableRow key={d.id} className={`${d.state === "failed" ? "bg-danger-soft" : ""}`}>
                <TableCell className="whitespace-nowrap">{vnTime(d.created_at)}</TableCell>
                <TableCell className="font-mono">{d.event}</TableCell>
                <TableCell>{d.recipient}</TableCell>
                <TableCell>{d.channel}</TableCell>
                <TableCell>
                  <Badge variant={deliveryStateTone(d.state, d.attempts)}>{deliveryStateLabel(d.state, d.attempts)}</Badge>
                </TableCell>
                <TableCell className="tabular-nums">{d.attempts}</TableCell>
                <TableCell className="max-w-[360px] break-words">{d.last_error || "—"}</TableCell>
                <TableCell className="text-right">
                  {d.state === "failed" && d.channel !== "in_app" ? (
                    <Button variant="outline" onClick={() => void retry({ ids: [d.id] })}>
                      Retry
                    </Button>
                  ) : (
                    "—"
                  )}
                </TableCell>
              </TableRow>
            ))}
            {page && page.items.length === 0 && (
              <TableRow>
                <TableCell colSpan={8} className="px-4 py-6 text-center text-muted-foreground">
                  No deliveries match these filters.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
      <p className="text-[11px] text-muted-foreground">
        {page ? `${Math.min(page.count, LIMIT)} of ${page.count} shown. ` : ""}A retry starts a fresh set of attempts and is recorded in the audit log.
      </p>
    </div>
  );
}
