"use client";

// One view per F10 report (Figma 17-1291 … 17-2311); each reads /api/reports/* and exports the same filters as CSV.

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { CurrentUser } from "@/lib/auth";
import { duration, percent } from "@/lib/format";
import type {
  ComplianceOut,
  CsatLineOut,
  CsatReportOut,
  IncidentReportOut,
  GraphHealthOut,
  KbReportOut,
  NotificationReportOut,
  ReviewerReportOut,
  RolloutReportOut,
  SecurityReportOut,
  SlaCellOut,
  SlaReportOut,
  SlaTicketPageOut,
  TeamOut,
  TeamReportOut,
} from "@/lib/types/generated";
import {
  Bar,
  Empty,
  ExportButton,
  Field,
  Header,
  MonthPicker,
  Stat,
  ReportTable,
  pickableTeams,
  query,
  thisMonth,
  useReport,
} from "./shared";
import { NativeSelect } from "@/components/ui/native-select";
import { Card } from "@/components/ui/card";
import { TableCell, TableRow } from "@/components/ui/table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";

function ratio(c: ComplianceOut): string {
  return `${c.met}/${c.met + c.breached}`;
}

function num(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "—" : v.toFixed(digits);
}

function Failed({ error }: { error: string | null }) {
  return error ? <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert> : null;
}

function useTeams(user: CurrentUser): string[] {
  const [all, setAll] = useState<string[]>([]);
  useEffect(() => {
    if (user.role !== "manager") return;
    api
      .get<TeamOut[]>("/api/teams")
      .then((r) => setAll(r.map((t) => t.slug)))
      .catch(() => setAll([]));
  }, [user]);
  return pickableTeams(user, all);
}

function TeamPicker({ user, value, onChange, allowAll }: { user: CurrentUser; value: string; onChange: (v: string) => void; allowAll: boolean }) {
  const teams = useTeams(user);
  return (
    <Field label="Team">
      <NativeSelect wrapperClassName="w-40" value={value} onChange={(e) => onChange(e.target.value)}>
        {allowAll && <option value="">all</option>}
        {teams.map((t) => (
          <option key={t}>{t}</option>
        ))}
      </NativeSelect>
    </Field>
  );
}

// ── SLA (17-1291) ──

function Cells({ title, cells, onPick }: { title: string; cells: SlaCellOut[]; onPick: (key: string) => void }) {
  return (
    <Card asChild>
      <section className="mb-4 p-4">
        <h2 className="mb-3 text-sm font-medium">{title}</h2>
        {cells.length === 0 ? (
          <p className="text-xs text-muted-foreground">No clock stopped this month.</p>
        ) : (
          <div className="flex flex-col gap-2">
            {cells.map((c) => (
              <button
                key={c.key}
                className="grid grid-cols-[120px_minmax(0,1fr)_150px] items-center gap-3 text-left text-sm hover:text-primary"
                onClick={() => onPick(c.key)}
              >
                <span>{c.key}</span>
                <Bar value={c.resolution.compliance} good={(c.resolution.compliance ?? 0) >= 0.9} />
                <span className="font-mono text-xs tabular-nums">
                  {percent(c.resolution.compliance)} ({ratio(c.resolution)})
                </span>
              </button>
            ))}
          </div>
        )}
      </section>
    </Card>
  );
}

export function SlaReport({ user }: { user: CurrentUser }) {
  const [month, setMonth] = useState(thisMonth());
  const [team, setTeam] = useState("");
  const [drill, setDrill] = useState<Record<string, string> | null>(null);
  const q = query({ month, team });
  const { data, error } = useReport<SlaReportOut>(`/api/reports/sla${q}`);
  const tickets = useReport<SlaTicketPageOut>(drill ? `/api/reports/sla/tickets${query({ month, team, ...drill })}` : null);
  return (
    <>
      <Header title="SLA compliance" note="Clocks that stopped in the period: met ÷ (met + late), in business hours.">
        <MonthPicker value={month} onChange={setMonth} />
        <TeamPicker user={user} value={team} onChange={setTeam} allowAll={user.role === "manager" || (user.teams ?? []).filter((t) => t.role === "lead").length > 1} />
        <ExportButton path={`/api/reports/sla.csv${q}`} filename={`sla-${month}.csv`} />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
            <Stat label="Resolution" value={percent(data.resolution.compliance)} note={`met ${ratio(data.resolution)} · target 90%`} />
            <Stat label="Response" value={percent(data.response.compliance)} note={`met ${ratio(data.response)}`} />
            <Stat label="Breached now" value={String(data.open_overdue_now)} note="running past due" tone={data.open_overdue_now ? "danger" : undefined} />
            <Stat
              label="Excluded"
              value={String(data.excluded.linked_incident + data.excluded.no_sla_data)}
              note={`${data.excluded.no_sla_data} without SLA data · ${data.excluded.linked_incident} linked to an incident`}
            />
          </div>
          <p className="mb-4 text-xs text-muted-foreground">
            Breaches warned in time: {percent(data.breaches_warned_in_time.rate)} ({data.breaches_warned_in_time.warned}/
            {data.breaches_warned_in_time.breached})
          </p>
          <Cells title="by priority" cells={data.by_priority} onPick={(k) => setDrill({ priority: k })} />
          <Cells title="by team" cells={data.by_team} onPick={(k) => setDrill({ team: k })} />
          <Cells title="by category" cells={data.by_category} onPick={(k) => setDrill({ category: k })} />
          <div className="mb-2 flex gap-3 text-xs">
            <Button variant="link" size="inline"  onClick={() => setDrill({ state: "breached" })}>
              breached tickets
            </Button>
            <Button variant="link" size="inline"  onClick={() => setDrill({ state: "excluded" })}>
              excluded tickets
            </Button>
          </div>
          {drill && tickets.data && (
            <ReportTable head={["Ticket", "Team", "Priority", "State", "Stopped at"]}>
              {tickets.data.items.map((t) => (
                <TableRow key={t.id}>
                  <TableCell>
                    <a className="text-primary hover:underline" href={`/tickets/${t.id}`}>
                      {t.public_id}
                    </a>
                    <div className="text-xs text-muted-foreground">{t.subject}</div>
                  </TableCell>
                  <TableCell>{t.team ?? "—"}</TableCell>
                  <TableCell>{t.priority ?? "—"}</TableCell>
                  <TableCell>{t.linked_incident ? "incident" : t.state}</TableCell>
                  <TableCell>{t.met_at ? new Date(t.met_at).toLocaleString("vi-VN") : "—"}</TableCell>
                </TableRow>
              ))}
            </ReportTable>
          )}
          <p className="mt-4 text-xs text-muted-foreground">
            Tickets linked to an incident ({data.excluded.linked_incident}) are reported on the Incidents tab, not counted here.
          </p>
        </>
      )}
    </>
  );
}

// ── Teams (17-1399) ──

export function TeamsReport({ user }: { user: CurrentUser }) {
  const own = (user.teams ?? []).map((t) => t.team);
  const teams = useTeams(user);
  const choices = user.role === "manager" ? teams : own;
  const [team, setTeam] = useState(own[0] ?? "");
  const slug = team || choices[0] || "";
  const { data, error } = useReport<TeamReportOut>(slug ? `/api/reports/teams/${slug}` : null);
  return (
    <>
      <Header title="Team workload" note="Open tickets by age (business days), time to assign, and moves between teams.">
        <Field label="Team">
          <NativeSelect wrapperClassName="w-40" value={slug} onChange={(e) => setTeam(e.target.value)}>
            {choices.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </NativeSelect>
        </Field>
        {slug && <ExportButton path={`/api/reports/teams/${slug}.csv`} filename={`team-${slug}.csv`} />}
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
            <Stat label="Unassigned now" value={String(data.unassigned_now)} />
            <Stat label="Time to assign" value={`${num(data.time_to_assign_median_min, 0)} phút`} note={`p90 ${num(data.time_to_assign_p90_min, 0)} phút`} />
            <Stat label="Reassignment" value={percent(data.reassignment_rate)} note={`${data.tickets_reassigned_cross_team}/${data.tickets_assigned} tickets`} />
            <Stat label="Period" value={`${data.start.slice(5)} → ${data.end.slice(5)}`} />
          </div>
          {data.members.length === 0 && (
            <Card className="mb-3">
              <Empty>This team has no members yet.</Empty>
            </Card>
          )}
          <ReportTable head={["Member", "Open", "0–1 days", "1–3", "3–5", "> 5", "Resolved", "Time to assign (median)", "In / out"]}>
            {data.members.map((m) => (
              <TableRow key={m.username}>
                <TableCell>
                  {m.display_name}
                  {m.role === "lead" && <span className="ml-1 text-xs text-muted-foreground">· lead</span>}
                </TableCell>
                <TableCell>{m.open_now}</TableCell>
                {Object.values(m.age_buckets).map((n, i) => (
                  <TableCell key={i} className={i === 3 && n > 0 ? "text-danger" : ""}>
                    {n}
                  </TableCell>
                ))}
                <TableCell>{m.resolved_in_period}</TableCell>
                <TableCell>{num(m.time_to_assign_median_min, 0)}</TableCell>
                <TableCell>
                  {m.reassigned_in} / {m.reassigned_out}
                </TableCell>
              </TableRow>
            ))}
          </ReportTable>
        </>
      )}
    </>
  );
}

// ── Reviewers (17-1631) ──

export function ReviewersReport() {
  const [days, setDays] = useState(30);
  const { data, error } = useReport<ReviewerReportOut>(`/api/reports/reviewers?days=${days}`);
  return (
    <>
      <Header title="Reviewers" note="Flagged when the approval rate is high and reading time short, once there are enough decisions to tell.">
        <Field label="Days">
          <NativeSelect wrapperClassName="w-28" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90].map((d) => (
              <option key={d}>{d}</option>
            ))}
          </NativeSelect>
        </Field>
        <ExportButton path={`/api/reports/reviewers.csv?days=${days}`} filename="reviewers.csv" />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <p className="mb-3 text-xs text-muted-foreground">
            Flagged at ≥ {data.min_decisions_for_flag} decisions, approval rate &gt; {percent(data.approve_rate_max)} and median &lt;{" "}
            {data.median_time_min_sec} s.
          </p>
          <ReportTable head={["Reviewer", "Decisions", "Approval rate", "Previous period", "Median", ""]}>
            {data.rows.map((r) => (
              <TableRow key={r.username}>
                <TableCell>{r.username}</TableCell>
                <TableCell>{r.decisions}</TableCell>
                <TableCell>{percent(r.approve_rate)}</TableCell>
                <TableCell>{percent(r.previous_approve_rate)}</TableCell>
                <TableCell>{duration(r.median_seconds)}</TableCell>
                <TableCell className="text-xs text-warn">
                  {r.flagged ? "May be approving by reflex" : r.decisions < data.min_decisions_for_flag ? "Not enough decisions yet" : ""}
                </TableCell>
              </TableRow>
            ))}
          </ReportTable>
        </>
      )}
    </>
  );
}

// ── KB (17-1765) ──

export function KbReport() {
  const { data, error } = useReport<KbReportOut>("/api/reports/kb");
  return (
    <>
      <Header title="KB health" note="Weekly refusal rate, open gap topics, and how much a gap closed after its page was published.">
        <ExportButton path="/api/reports/kb.csv" filename="kb.csv" />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
            <Stat label="Open gaps" value={String(data.open_clusters)} note={Object.entries(data.open_by_label).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"} />
            <Stat label="Refused this week" value={percent(data.refusals.at(-1)?.refusal_rate ?? null)} />
            <Stat label="Closures" value={String(data.closures.length)} />
          </div>
          <Card asChild>
            <section className="mb-4 p-4">
              <h2 className="mb-3 text-sm font-medium">Weekly refusal rate</h2>
              <div className="flex flex-col gap-2">
                {data.refusals.map((w) => (
                  <div key={w.week_start} className="grid grid-cols-[100px_minmax(0,1fr)_140px] items-center gap-3 text-sm">
                    <span className="font-mono text-xs">{w.week_start}</span>
                    <Bar value={w.refusal_rate} good={(w.refusal_rate ?? 0) < 0.1} />
                    <span className="font-mono text-xs tabular-nums">
                      {percent(w.refusal_rate)} ({w.refused}/{w.decisions})
                    </span>
                  </div>
                ))}
              </div>
            </section>
          </Card>
          {data.closures.length === 0 ? (
            <Card>
              <Empty>No page has been written from a gap topic yet.</Empty>
            </Card>
          ) : (
            <ReportTable head={["Page", "Before", "After", "Closed", ""]}>
              {data.closures.map((c) => (
                <TableRow key={c.cluster_id}>
                  <TableCell className="font-mono">{c.article_slug ?? c.cluster_id}</TableCell>
                  <TableCell>{c.before}</TableCell>
                  <TableCell>{c.after}</TableCell>
                  <TableCell>{percent(c.closure, 0)}</TableCell>
                  <TableCell className="text-xs text-muted-foreground">{c.complete ? "" : "less than 4 weeks"}</TableCell>
                </TableRow>
              ))}
            </ReportTable>
          )}
          <GraphHealth graph={data.graph} />
        </>
      )}
    </>
  );
}

// ── Graph health (F11, 17-1912) ──

function GraphHealth({ graph }: { graph: GraphHealthOut }) {
  return (
    <section className="mt-6">
      <h2 className="mb-1 text-sm font-medium">Graph health</h2>
      <p className="mb-3 text-xs text-muted-foreground">
        The links search follows; scores never decide an automatic answer.
      </p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <Stat
          label="Pages with edges"
          value={`${graph.pages_with_edges} / ${graph.pages}`}
          note={`${graph.edges} links`}
        />
        <Stat
          label="Stale edges"
          value={String(graph.stale_edges)}
          tone={graph.stale_edges > 0 ? "warn" : undefined}
          note={`${graph.pending_requests} pages waiting to rebuild · ${graph.failed_requests} failed`}
        />
        <Stat label="Overrides" value={String(graph.hidden + graph.added)} note={`${graph.hidden} hidden · ${graph.added} added`} />
        <Stat
          label="From expansion"
          value={percent(graph.expansion_share)}
          note={`${graph.auto_replies_from_expansion}/${graph.auto_replies} automatic answers in the period`}
        />
      </div>
    </section>
  );
}

// ── CSAT (17-1916) ──

function CsatCard({ title, line }: { title: string; line: CsatLineOut }) {
  const max = Math.max(1, ...Object.values(line.distribution));
  return (
    <Card asChild>
      <section className="p-4">
        <h2 className="text-sm font-medium">{title}</h2>
        <p className="mt-1 text-2xl font-semibold tabular-nums">{num(line.mean, 2)}</p>
        <p className="text-xs text-muted-foreground">
          {line.ratings} ratings · response rate {percent(line.response_rate)} ({line.ratings}/{line.resolved})
        </p>
        <div className="mt-3 flex flex-col gap-1">
          {["5", "4", "3", "2", "1"].map((s) => (
            <div key={s} className="grid grid-cols-[24px_minmax(0,1fr)_40px] items-center gap-2 text-xs">
              <span>{s}★</span>
              <Bar value={line.distribution[s] / max} good={Number(s) >= 4} />
              <span className="text-right font-mono">{line.distribution[s]}</span>
            </div>
          ))}
        </div>
      </section>
    </Card>
  );
}

export function CsatReport({ user }: { user: CurrentUser }) {
  const [month, setMonth] = useState(thisMonth());
  const [team, setTeam] = useState("");
  const q = query({ month, team });
  const { data, error } = useReport<CsatReportOut>(`/api/reports/csat${q}`);
  return (
    <>
      <Header title="CSAT" note="Automatic answers and staff-handled tickets are different services, so they are always reported separately.">
        <MonthPicker value={month} onChange={setMonth} />
        <TeamPicker user={user} value={team} onChange={setTeam} allowAll />
        <ExportButton path={`/api/reports/csat.csv${q}`} filename={`csat-${month}.csv`} />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <CsatCard title="Handled by a person" line={data.person} />
            <CsatCard title="Auto-replied" line={data.auto} />
          </div>
          {data.by_team.length > 0 && (
            <div className="mb-4">
              <ReportTable head={["Team", "Staff", "Automatic", "Ratings"]}>
                {data.by_team.map((t) => (
                  <TableRow key={t.team}>
                    <TableCell>{t.team}</TableCell>
                    <TableCell>{num(t.person.mean, 2)}</TableCell>
                    <TableCell>{num(t.auto.mean, 2)}</TableCell>
                    <TableCell>{t.person.ratings + t.auto.ratings}</TableCell>
                  </TableRow>
                ))}
              </ReportTable>
            </div>
          )}
          <Card asChild>
            <section className="p-4">
              <h2 className="mb-2 text-sm font-medium">Low ratings (personal data masked)</h2>
              {data.low_rated.length === 0 ? (
                <p className="text-xs text-muted-foreground">None.</p>
              ) : (
                <ul className="flex flex-col gap-2 text-sm">
                  {data.low_rated.map((r) => (
                    <li key={`${r.ticket_public_id}-${r.rated_at}`}>
                      <span className="font-mono text-xs">{r.ticket_public_id}</span> · {r.score}★ · {r.team ?? "—"}
                      <p className="text-muted-foreground">{r.comment}</p>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </Card>
        </>
      )}
    </>
  );
}

// ── Rollout readiness (17-2028) ──

export function RolloutReport() {
  const { data, error } = useReport<RolloutReportOut>("/api/reports/rollout");
  return (
    <>
      <Header title="Rollout readiness" note="The same figures the rollout gates read.">
        <ExportButton path="/api/reports/rollout.csv" filename="rollout.csv" />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <Stat label="Automation live" value={percent(data.automation.live_rate)} note="not a target" />
            <Stat label="would-have" value={percent(data.automation.would_have_rate)} note="not a target" />
          </div>
          <ReportTable head={["Branch", "Live", "Agreement", "Reviewed", "Coverage", "Gates met"]}>
            {data.branches.map((b) => (
              <TableRow key={b.branch}>
                <TableCell className="font-mono">{b.branch}</TableCell>
                <TableCell>{b.live ? "live" : "shadow"}</TableCell>
                <TableCell>{percent(b.agreement.rate)}</TableCell>
                <TableCell>
                  {b.agreement.agreed}/{b.agreement.decided}
                </TableCell>
                <TableCell>{percent(b.coverage)}</TableCell>
                <TableCell>
                  {b.gates.filter((g) => g.met).length}/{b.gates.length}
                </TableCell>
              </TableRow>
            ))}
          </ReportTable>
          <p className="mt-3 text-xs text-muted-foreground">Last {data.days} days.</p>
        </>
      )}
    </>
  );
}

// ── Security (17-2164) ──

export function SecurityReport() {
  const [month, setMonth] = useState(thisMonth());
  const { data, error } = useReport<SecurityReportOut>(`/api/reports/security?month=${month}`);
  return (
    <>
      <Header title="Security" note="Managers see counts by kind only; the alerts themselves are for security.">
        <MonthPicker value={month} onChange={setMonth} />
        <ExportButton path={`/api/reports/security.csv?month=${month}`} filename={`security-${month}.csv`} />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
            <Stat label="Alerts" value={String(data.total)} />
            {data.detail && (
              <>
                <Stat label="Ack p50" value={duration(data.ack_p50_sec)} note={`p90 ${duration(data.ack_p90_sec)}`} />
                <Stat label="Ack in target (K12)" value={`${data.ack_in_target ?? 0}/${data.acknowledged ?? 0}`} />
                <Stat label="False positive" value={percent(data.false_positive_rate)} note={`${data.false_positive ?? 0}/${data.closed ?? 0} closed`} />
              </>
            )}
          </div>
          <ReportTable head={["Kind", "Count", "Open"]}>
            {data.by_kind.map((k) => (
              <TableRow key={k.kind}>
                <TableCell className="font-mono">{k.kind}</TableCell>
                <TableCell>{k.count}</TableCell>
                <TableCell>{k.open}</TableCell>
              </TableRow>
            ))}
          </ReportTable>
        </>
      )}
    </>
  );
}

// ── Incidents (17-2311) ──

export function IncidentsReport() {
  const [month, setMonth] = useState(thisMonth());
  const { data, error } = useReport<IncidentReportOut>(`/api/reports/incidents?month=${month}`);
  return (
    <>
      <Header title="Incidents" note="Time to confirm, time to the first broadcast, and the unlink rate (how precise the detector is).">
        <MonthPicker value={month} onChange={setMonth} />
        <ExportButton path={`/api/reports/incidents.csv?month=${month}`} filename={`incidents-${month}.csv`} />
      </Header>
      <Failed error={error} />
      {data && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <Stat label="Detected" value={String(data.detected)} note={`${data.confirmed} confirmed · ${data.dismissed} dismissed`} />
          <Stat label="Linked tickets" value={String(data.linked_tickets)} />
          <Stat label="Time to confirm" value={duration(data.confirm_p50_sec)} />
          <Stat label="First broadcast" value={duration(data.first_broadcast_p50_sec)} note={`p90 ${duration(data.first_broadcast_p90_sec)} · target ≤ 15 min`} />
          <Stat label="Unlink rate" value={percent(data.unlink_rate)} note={`${data.links_unlinked}/${data.links_created} links`} />
        </div>
      )}
    </>
  );
}

// ── Notifications (FR-F10-012) ──

export function NotificationsReport() {
  const [days, setDays] = useState(7);
  const { data, error } = useReport<NotificationReportOut>(`/api/reports/notifications?days=${days}`);
  return (
    <>
      <Header title="Notifications" note="p95 delay from creation to sending, and failures by channel.">
        <Field label="Days">
          <NativeSelect wrapperClassName="w-28" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 30].map((d) => (
              <option key={d}>{d}</option>
            ))}
          </NativeSelect>
        </Field>
        <ExportButton path={`/api/reports/notifications.csv?days=${days}`} filename="notifications.csv" />
      </Header>
      <Failed error={error} />
      {data && (
        <ReportTable head={["Channel", "Messages", "Sent", "Failed", "p95 delay"]}>
          {data.channels.map((c) => (
            <TableRow key={c.channel}>
              <TableCell className="font-mono">{c.channel}</TableCell>
              <TableCell>{c.messages}</TableCell>
              <TableCell>{c.delivered}</TableCell>
              <TableCell className={c.failed ? "text-danger" : ""}>{c.failed}</TableCell>
              <TableCell>{duration(c.latency_p95_sec)}</TableCell>
            </TableRow>
          ))}
        </ReportTable>
      )}
    </>
  );
}
