"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRequireAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { duration, percent } from "@/lib/format";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

interface DashboardData {
  quality: {
    reopen_rate_after_autoreply: number | null;
    override_rate: number | null;
    reroute_rate: number | null;
    refusal_rate: number | null;
    hallucination_catch_rate: number | null;
    override_rate_by_category: { review_item__ticket__category: string | null; n: number }[];
  };
  hitl_health: {
    queue_depth_by_queue: { queue: string; n: number }[];
    time_in_queue_p50_sec: number | null;
    time_in_queue_p95_sec: number | null;
    approve_rate_per_reviewer: { reviewer__username: string; total: number; approve_rate: number | null; median_time_spent_sec: number | null }[];
  };
  ops: {
    latency_p50_ms: number | null;
    latency_p95_ms: number | null;
    cost_per_ticket_usd: number | null;
    degraded_run_ratio: number | null;
    circuit_open_events: number;
  };
  business: {
    automation_rate_live: number | null;
    automation_rate_would_have: number | null;
    sla_compliance: number | null;
  };
}

function Headline({ label, value, note, warn = false }: { label: string; value: string; note: string; warn?: boolean }) {
  return (
    <Card className="p-5">
      <p className="text-sm text-muted-foreground">{label}</p>
      <p className={`mt-1 text-3xl font-semibold tabular-nums tracking-tight ${warn ? "text-danger" : ""}`}>{value}</p>
      <p className="mt-2 text-xs leading-5 text-muted-foreground">{note}</p>
    </Card>
  );
}

function Rows({ title, rows }: { title: string; rows: { label: string; value: string; note: string }[] }) {
  return (
    <Card asChild>
      <section>
        <h2 className="border-b border-border px-5 py-3 text-sm font-semibold">{title}</h2>
        <dl>
          {rows.map((r) => (
            <div key={r.label} className="grid grid-cols-[minmax(0,1fr)_110px] gap-4 border-b border-border px-5 py-3 last:border-0">
              <div>
                <dt className="text-sm">{r.label}</dt>
                <p className="text-xs text-muted-foreground">{r.note}</p>
              </div>
              <dd className="text-right font-mono text-sm tabular-nums">{r.value}</dd>
            </div>
          ))}
        </dl>
      </section>
    </Card>
  );
}

const WINDOW_DAYS = 30;

export default function DashboardPage() {
  const user = useRequireAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    api
      .get<DashboardData>(`/api/metrics/dashboard?window_days=${WINDOW_DAYS}`)
      .then(setData)
      .catch(() => setError("Couldn't load the dashboard."));
  }, [user]);

  if (!user) return null;
  if (error) return <p className="text-sm text-danger">{error}</p>;
  if (!data) return <p className="text-sm text-muted-foreground">Loading…</p>;

  const waiting = data.hitl_health.queue_depth_by_queue.reduce((sum, q) => sum + q.n, 0);
  const reopen = data.quality.reopen_rate_after_autoreply;

  return (
    <div className="mx-auto max-w-[1280px]">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-0.5 text-sm text-muted-foreground">
          Last {WINDOW_DAYS} days · full reports under{" "}
          <Link href="/admin/reports" className="text-primary hover:underline">
            Báo cáo · Reports
          </Link>
        </p>
      </header>

      <div className="mb-6 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Headline
          label="Reopened after an automatic answer"
          value={percent(reopen)}
          note="The number that matters most: an automatic answer that was wrong but closed the ticket stays invisible until the requester reopens it."
          warn={reopen !== null && reopen > 0.05}
        />
        <Headline
          label="Tự động hoá (thực tế) · Automation, live"
          value={percent(data.business.automation_rate_live)}
          note={`Carried out without a person. Would have, counting shadow decisions: ${percent(data.business.automation_rate_would_have)}. Not a target (BR-F10-09).`}
        />
        <Headline
          label="SLA giải quyết · Resolution SLA"
          value={percent(data.business.sla_compliance)}
          note="Resolution clocks stopped in the period that met their target, in business time; incident-linked tickets excluded (BR-F10-02)."
        />
        <Headline
          label="Waiting for review"
          value={String(waiting)}
          note={`Half wait under ${duration(data.hitl_health.time_in_queue_p50_sec)}; the slowest 5% wait over ${duration(data.hitl_health.time_in_queue_p95_sec)}.`}
        />
      </div>

      <div className="grid grid-cols-1 gap-6 xl:grid-cols-2">
        <Rows
          title="Quality of AI decisions"
          rows={[
            { label: "Overridden by a reviewer", value: percent(data.quality.override_rate), note: "Reviews where the person did something other than approve." },
            { label: "Rerouted", value: percent(data.quality.reroute_rate), note: "Sent to a different team than proposed." },
            { label: "Refused to answer", value: percent(data.quality.refusal_rate), note: "No help page matched well enough, so no answer was attempted." },
            { label: "Bad answers caught", value: percent(data.quality.hallucination_catch_rate), note: "Answers the checks stopped because they misquoted or contradicted the page." },
          ]}
        />
        <Rows
          title="System"
          rows={[
            { label: "Time to triage (median)", value: duration((data.ops.latency_p50_ms ?? 0) / 1000), note: "From submission to a routing decision." },
            { label: "Time to triage (slowest 5%)", value: duration((data.ops.latency_p95_ms ?? 0) / 1000), note: "Cold model loads land here." },
            { label: "AI cost per ticket", value: data.ops.cost_per_ticket_usd === null ? "—" : `$${data.ops.cost_per_ticket_usd.toFixed(4)}`, note: "Model and API spend, averaged." },
            { label: "Degraded runs", value: percent(data.ops.degraded_run_ratio), note: "Runs where part of the AI was down, so a person took over." },
          ]}
        />
      </div>

      <Card asChild>
        <section className="mt-6">
          <h2 className="border-b border-border px-5 py-3 text-sm font-semibold">Reviewers</h2>
          {data.hitl_health.approve_rate_per_reviewer.length === 0 ? (
            <p className="px-5 py-4 text-sm text-muted-foreground">No reviews in this period.</p>
          ) : (
            <Table className="w-full text-sm">
              <TableHeader className="text-left text-xs text-muted-foreground">
                <TableRow>
                  <TableHead className="px-5 py-2 font-medium">Reviewer</TableHead>
                  <TableHead className="px-5 py-2 text-right font-medium">Reviews</TableHead>
                  <TableHead className="px-5 py-2 text-right font-medium">Approved as proposed</TableHead>
                  <TableHead className="px-5 py-2 text-right font-medium">Median time per review</TableHead>
                  <TableHead className="px-5 py-2 font-medium" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {data.hitl_health.approve_rate_per_reviewer.map((r) => {
                  const rushed = r.median_time_spent_sec !== null && r.median_time_spent_sec < 10;
                  return (
                    <TableRow key={r.reviewer__username} className="border-t border-border">
                      <TableCell className="px-5 py-2.5">{r.reviewer__username}</TableCell>
                      <TableCell className="px-5 py-2.5 text-right font-mono tabular-nums">{r.total}</TableCell>
                      <TableCell className="px-5 py-2.5 text-right font-mono tabular-nums">{percent(r.approve_rate)}</TableCell>
                      <TableCell className="px-5 py-2.5 text-right font-mono tabular-nums">{duration(r.median_time_spent_sec)}</TableCell>
                      <TableCell className="px-5 py-2.5 text-xs text-warn">{rushed ? "Under 10 s: may not be reading" : ""}</TableCell>
                    </TableRow>
                  );
                })}
              </TableBody>
            </Table>
          )}
        </section>
      </Card>
    </div>
  );
}
