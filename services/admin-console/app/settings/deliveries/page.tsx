"use client";

// The delivery log (F4 · 11-890): email and webhook messages, failures to retry.

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { deliveryStateClasses, deliveryStateLabel } from "@/lib/badges";
import type { DeliveryOut, RetryOut } from "@/lib/types/generated";

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
      <span className="text-[11px] text-[var(--text-muted)]">{label}</span>
      <select value={value} onChange={(e) => onChange(e.target.value)} className="field">
        {options.map((o) => (
          <option key={o} value={o}>
            {o || "All"}
          </option>
        ))}
      </select>
    </label>
  );

  const failed = page?.items.some((d) => d.state === "failed") ?? false;

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Delivery log</h1>
          <p className="text-xs text-[var(--text-muted)]">Email and webhook messages. A failed send never changes the ticket.</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          {select("Channel", channel, CHANNELS, setChannel)}
          {select("State", state, STATES, setState)}
          {state === "failed" && failed && (
            <button className="btn btn-secondary" onClick={() => void retry({ all_failed: true })}>
              Retry all failed
            </button>
          )}
        </div>
      </header>

      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
      {notice && <p className="text-sm text-[var(--ok)]">{notice}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-xs">
          <thead className="bg-[var(--bg)] text-[11px] text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2 font-normal">Created (+07)</th>
              <th className="px-4 py-2 font-normal">Event</th>
              <th className="px-4 py-2 font-normal">Recipient</th>
              <th className="px-4 py-2 font-normal">Channel</th>
              <th className="px-4 py-2 font-normal">State</th>
              <th className="px-4 py-2 font-normal">Attempts</th>
              <th className="px-4 py-2 font-normal">Error</th>
              <th className="px-4 py-2 font-normal" />
            </tr>
          </thead>
          <tbody>
            {page?.items.map((d) => (
              <tr key={d.id} className={`border-t border-[var(--border)] ${d.state === "failed" ? "bg-[var(--danger-soft)]" : ""}`}>
                <td className="whitespace-nowrap px-4 py-2.5">{vnTime(d.created_at)}</td>
                <td className="px-4 py-2.5 font-mono">{d.event}</td>
                <td className="px-4 py-2.5">{d.recipient}</td>
                <td className="px-4 py-2.5">{d.channel}</td>
                <td className="px-4 py-2.5">
                  <span className={`badge ${deliveryStateClasses(d.state, d.attempts)}`}>{deliveryStateLabel(d.state, d.attempts)}</span>
                </td>
                <td className="px-4 py-2.5 tabular-nums">{d.attempts}</td>
                <td className="max-w-[360px] px-4 py-2.5 break-words">{d.last_error || "—"}</td>
                <td className="px-4 py-2.5 text-right">
                  {d.state === "failed" && d.channel !== "in_app" ? (
                    <button className="btn btn-secondary" onClick={() => void retry({ ids: [d.id] })}>
                      Retry
                    </button>
                  ) : (
                    "—"
                  )}
                </td>
              </tr>
            ))}
            {page && page.items.length === 0 && (
              <tr>
                <td colSpan={8} className="px-4 py-6 text-center text-[var(--text-muted)]">
                  No deliveries match these filters.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        {page ? `${Math.min(page.count, LIMIT)} of ${page.count} shown. ` : ""}A retry starts a fresh set of attempts and is recorded in the audit log.
      </p>
    </div>
  );
}
