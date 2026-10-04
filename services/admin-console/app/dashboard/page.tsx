"use client";

import { useEffect, useState } from "react";
import { useRequireAuth } from "@/lib/auth";
import { api } from "@/lib/api";

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
    automation_rate: number | null;
    sla_compliance: number | null;
  };
}

function pct(v: number | null): string {
  return v === null ? "—" : `${(v * 100).toFixed(1)}%`;
}

function num(v: number | null, digits = 0): string {
  return v === null ? "—" : v.toFixed(digits);
}

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-4">
      <div className="text-xs uppercase tracking-wide text-[var(--text-muted)]">{label}</div>
      <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <div className="mt-1 text-xs text-[var(--text-muted)]">{hint}</div>}
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mb-8">
      <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-[var(--text-muted)]">{title}</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 lg:grid-cols-5">{children}</div>
    </section>
  );
}

export default function DashboardPage() {
  const user = useRequireAuth();
  const [data, setData] = useState<DashboardData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    api
      .get<DashboardData>("/api/metrics/dashboard?window_days=30")
      .then(setData)
      .catch(() => setError("Failed to load dashboard metrics."));
  }, [user]);

  if (!user) return null;
  if (error) return <p className="text-sm text-red-600">{error}</p>;
  if (!data) return <p className="text-sm text-[var(--text-muted)]">Loading…</p>;

  return (
    <div>
      <h1 className="mb-1 text-xl font-semibold">Dashboard</h1>
      <p className="mb-6 text-sm text-[var(--text-muted)]">
        Quality first — the reopen rate after auto-reply is the single most important number here (spec §11.1: a
        wrong auto-reply that closes the ticket is an invisible failure).
      </p>

      <Section title="Quality">
        <StatTile
          label="Reopen rate after auto-reply"
          value={pct(data.quality.reopen_rate_after_autoreply)}
          hint="metric #1"
        />
        <StatTile label="Override rate" value={pct(data.quality.override_rate)} />
        <StatTile label="Reroute rate" value={pct(data.quality.reroute_rate)} />
        <StatTile label="Refusal rate" value={pct(data.quality.refusal_rate)} />
        <StatTile label="Hallucination catch rate" value={pct(data.quality.hallucination_catch_rate)} />
      </Section>

      <Section title="HITL health">
        <StatTile label="Queue depth (total)" value={String(data.hitl_health.queue_depth_by_queue.reduce((s, q) => s + q.n, 0))} />
        <StatTile label="Time in queue p50" value={num(data.hitl_health.time_in_queue_p50_sec)} hint="seconds" />
        <StatTile label="Time in queue p95" value={num(data.hitl_health.time_in_queue_p95_sec)} hint="seconds" />
        {data.hitl_health.approve_rate_per_reviewer.map((r) => (
          <StatTile
            key={r.reviewer__username}
            label={`${r.reviewer__username} approve rate`}
            value={pct(r.approve_rate)}
            hint={
              r.median_time_spent_sec !== null && r.median_time_spent_sec < 10
                ? "⚠ median < 10s — may not be reading"
                : undefined
            }
          />
        ))}
      </Section>

      <Section title="Operations">
        <StatTile label="Latency p50" value={num(data.ops.latency_p50_ms)} hint="ms" />
        <StatTile label="Latency p95" value={num(data.ops.latency_p95_ms)} hint="ms" />
        <StatTile label="Cost per ticket" value={data.ops.cost_per_ticket_usd === null ? "—" : `$${data.ops.cost_per_ticket_usd.toFixed(4)}`} />
        <StatTile label="Degraded run ratio" value={pct(data.ops.degraded_run_ratio)} />
        <StatTile label="Circuit-open events" value={String(data.ops.circuit_open_events)} />
      </Section>

      <Section title="Business">
        <StatTile label="Automation rate" value={pct(data.business.automation_rate)} hint="(auto_reply + auto_route) / total" />
        <StatTile label="SLA compliance" value={pct(data.business.sla_compliance)} />
      </Section>
    </div>
  );
}
