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
  Table,
  pickableTeams,
  query,
  thisMonth,
  useReport,
} from "./shared";

function ratio(c: ComplianceOut): string {
  return `${c.met}/${c.met + c.breached}`;
}

function num(v: number | null | undefined, digits = 1): string {
  return v === null || v === undefined ? "—" : v.toFixed(digits);
}

function Failed({ error }: { error: string | null }) {
  return error ? <p className="tone-danger mb-3 rounded-[5px] px-3 py-2 text-sm">{error}</p> : null;
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
    <Field label="Nhóm · Team">
      <select className="field w-40" value={value} onChange={(e) => onChange(e.target.value)}>
        {allowAll && <option value="">tất cả · all</option>}
        {teams.map((t) => (
          <option key={t}>{t}</option>
        ))}
      </select>
    </Field>
  );
}

// ── SLA (17-1291) ──

function Cells({ title, cells, onPick }: { title: string; cells: SlaCellOut[]; onPick: (key: string) => void }) {
  return (
    <section className="card mb-4 p-4">
      <h2 className="mb-3 text-sm font-medium">{title}</h2>
      {cells.length === 0 ? (
        <p className="text-xs text-[var(--text-muted)]">Không có đồng hồ nào dừng trong tháng.</p>
      ) : (
        <div className="flex flex-col gap-2">
          {cells.map((c) => (
            <button
              key={c.key}
              className="grid grid-cols-[120px_minmax(0,1fr)_150px] items-center gap-3 text-left text-sm hover:text-[var(--accent)]"
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
      <Header title="Tuân thủ SLA · SLA compliance" note="Đồng hồ dừng trong kỳ: đạt ÷ (đạt + trễ), theo giờ làm việc (BR-F10-01).">
        <MonthPicker value={month} onChange={setMonth} />
        <TeamPicker user={user} value={team} onChange={setTeam} allowAll={user.role === "manager" || (user.teams ?? []).filter((t) => t.role === "lead").length > 1} />
        <ExportButton path={`/api/reports/sla.csv${q}`} filename={`sla-${month}.csv`} />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
            <Stat label="SLA giải quyết · Resolution" value={percent(data.resolution.compliance)} note={`đạt ${ratio(data.resolution)} · mục tiêu 90 %`} />
            <Stat label="SLA phản hồi · Response" value={percent(data.response.compliance)} note={`đạt ${ratio(data.response)}`} />
            <Stat label="Đang trễ · Breached now" value={String(data.open_overdue_now)} note="đang chạy quá hạn" tone={data.open_overdue_now ? "danger" : undefined} />
            <Stat
              label="Loại trừ · Excluded"
              value={String(data.excluded.linked_incident + data.excluded.no_sla_data)}
              note={`${data.excluded.no_sla_data} không có dữ liệu SLA (BR-F10-03) · ${data.excluded.linked_incident} gắn sự cố`}
            />
          </div>
          <p className="mb-4 text-xs text-[var(--text-muted)]">
            Trễ được cảnh báo kịp (K3): {percent(data.breaches_warned_in_time.rate)} ({data.breaches_warned_in_time.warned}/
            {data.breaches_warned_in_time.breached})
          </p>
          <Cells title="SLA giải quyết theo ưu tiên · by priority" cells={data.by_priority} onPick={(k) => setDrill({ priority: k })} />
          <Cells title="Theo nhóm · by team" cells={data.by_team} onPick={(k) => setDrill({ team: k })} />
          <Cells title="Theo loại · by category" cells={data.by_category} onPick={(k) => setDrill({ category: k })} />
          <div className="mb-2 flex gap-3 text-xs">
            <button className="text-[var(--accent)] hover:underline" onClick={() => setDrill({ state: "breached" })}>
              Xem phiếu trễ · breached tickets
            </button>
            <button className="text-[var(--accent)] hover:underline" onClick={() => setDrill({ state: "excluded" })}>
              Xem phiếu bị loại · excluded tickets
            </button>
          </div>
          {drill && tickets.data && (
            <Table head={["Phiếu · Ticket", "Nhóm", "Ưu tiên", "Trạng thái", "Dừng lúc"]}>
              {tickets.data.items.map((t) => (
                <tr key={t.id}>
                  <td>
                    <a className="text-[var(--accent)] hover:underline" href={`/tickets/${t.id}`}>
                      {t.public_id}
                    </a>
                    <div className="text-xs text-[var(--text-muted)]">{t.subject}</div>
                  </td>
                  <td>{t.team ?? "—"}</td>
                  <td>{t.priority ?? "—"}</td>
                  <td>{t.linked_incident ? "sự cố" : t.state}</td>
                  <td>{t.met_at ? new Date(t.met_at).toLocaleString("vi-VN") : "—"}</td>
                </tr>
              ))}
            </Table>
          )}
          <p className="mt-4 text-xs text-[var(--text-muted)]">
            Phiếu gắn sự cố ({data.excluded.linked_incident}) được báo cáo ở tab Sự cố, không tính ở đây (BR-F10-04).
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
      <Header title="Khối lượng nhóm · Team workload" note="Phiếu đang mở theo tuổi (ngày làm việc), thời gian giao việc (K4), chuyển nhóm (K5).">
        <Field label="Nhóm · Team">
          <select className="field w-40" value={slug} onChange={(e) => setTeam(e.target.value)}>
            {choices.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
        </Field>
        {slug && <ExportButton path={`/api/reports/teams/${slug}.csv`} filename={`team-${slug}.csv`} />}
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
            <Stat label="Chưa giao · Unassigned now" value={String(data.unassigned_now)} />
            <Stat label="Giao việc (trung vị) · Time to assign" value={`${num(data.time_to_assign_median_min, 0)} phút`} note={`p90 ${num(data.time_to_assign_p90_min, 0)} phút`} />
            <Stat label="Tỷ lệ chuyển nhóm · Reassignment" value={percent(data.reassignment_rate)} note={`${data.tickets_reassigned_cross_team}/${data.tickets_assigned} phiếu`} />
            <Stat label="Kỳ · Period" value={`${data.start.slice(5)} → ${data.end.slice(5)}`} />
          </div>
          {data.members.length === 0 && (
            <div className="card mb-3">
              <Empty>Nhóm chưa có thành viên.</Empty>
            </div>
          )}
          <Table head={["Thành viên", "Đang mở", "0–1 ngày", "1–3", "3–5", "> 5", "Đã giải quyết", "Giao (trung vị)", "Nhận / chuyển đi"]}>
            {data.members.map((m) => (
              <tr key={m.username}>
                <td>
                  {m.display_name}
                  {m.role === "lead" && <span className="ml-1 text-xs text-[var(--text-muted)]">· lead</span>}
                </td>
                <td>{m.open_now}</td>
                {Object.values(m.age_buckets).map((n, i) => (
                  <td key={i} className={i === 3 && n > 0 ? "text-[var(--danger)]" : ""}>
                    {n}
                  </td>
                ))}
                <td>{m.resolved_in_period}</td>
                <td>{num(m.time_to_assign_median_min, 0)}</td>
                <td>
                  {m.reassigned_in} / {m.reassigned_out}
                </td>
              </tr>
            ))}
          </Table>
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
      <Header title="Người duyệt · Reviewers" note="Đánh dấu khi tỷ lệ duyệt cao và thời gian đọc ngắn, chỉ khi đủ số quyết định (BR-F10-06).">
        <Field label="Số ngày · Days">
          <select className="field w-28" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[7, 30, 90].map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </Field>
        <ExportButton path={`/api/reports/reviewers.csv?days=${days}`} filename="reviewers.csv" />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <p className="mb-3 text-xs text-[var(--text-muted)]">
            Đánh dấu: ≥ {data.min_decisions_for_flag} quyết định, tỷ lệ duyệt &gt; {percent(data.approve_rate_max)} và trung vị &lt;{" "}
            {data.median_time_min_sec} s.
          </p>
          <Table head={["Người duyệt", "Quyết định", "Tỷ lệ duyệt", "Kỳ trước", "Trung vị", ""]}>
            {data.rows.map((r) => (
              <tr key={r.username}>
                <td>{r.username}</td>
                <td>{r.decisions}</td>
                <td>{percent(r.approve_rate)}</td>
                <td>{percent(r.previous_approve_rate)}</td>
                <td>{duration(r.median_seconds)}</td>
                <td className="text-xs text-[var(--warn)]">
                  {r.flagged ? "⚠ có thể duyệt theo phản xạ" : r.decisions < data.min_decisions_for_flag ? "chưa đủ mẫu" : ""}
                </td>
              </tr>
            ))}
          </Table>
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
      <Header title="Sức khoẻ KB · KB health" note="Tỷ lệ từ chối theo tuần, chủ đề thiếu đang mở, và mức đóng khoảng trống sau khi xuất bản trang (BR-F10-07).">
        <ExportButton path="/api/reports/kb.csv" filename="kb.csv" />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-3">
            <Stat label="Chủ đề thiếu đang mở · Open gaps" value={String(data.open_clusters)} note={Object.entries(data.open_by_label).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"} />
            <Stat label="Từ chối tuần này · Refused this week" value={percent(data.refusals.at(-1)?.refusal_rate ?? null)} />
            <Stat label="Trang đã đóng khoảng trống · Closures" value={String(data.closures.length)} />
          </div>
          <section className="card mb-4 p-4">
            <h2 className="mb-3 text-sm font-medium">Tỷ lệ từ chối theo tuần · Weekly refusal rate</h2>
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
          {data.closures.length === 0 ? (
            <div className="card">
              <Empty>Chưa có trang nào được viết từ một chủ đề thiếu.</Empty>
            </div>
          ) : (
            <Table head={["Trang · Page", "Trước", "Sau", "Đóng", ""]}>
              {data.closures.map((c) => (
                <tr key={c.cluster_id}>
                  <td className="font-mono">{c.article_slug ?? c.cluster_id}</td>
                  <td>{c.before}</td>
                  <td>{c.after}</td>
                  <td>{percent(c.closure, 0)}</td>
                  <td className="text-xs text-[var(--text-muted)]">{c.complete ? "" : "chưa đủ 4 tuần"}</td>
                </tr>
              ))}
            </Table>
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
      <h2 className="mb-1 text-sm font-medium">Đồ thị liên kết · Graph health</h2>
      <p className="mb-3 text-xs text-[var(--text-muted)]">
        Các liên kết mở rộng tìm kiếm theo; điểm không bao giờ quyết định trả lời tự động (BR-F11-04).
      </p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <Stat
          label="Trang có liên kết · Pages with edges"
          value={`${graph.pages_with_edges} / ${graph.pages}`}
          note={`${graph.edges} liên kết`}
        />
        <Stat
          label="Liên kết cũ · Stale edges"
          value={String(graph.stale_edges)}
          tone={graph.stale_edges > 0 ? "warn" : undefined}
          note={`${graph.pending_requests} trang chờ dựng lại · ${graph.failed_requests} lỗi`}
        />
        <Stat label="Điều chỉnh · Overrides" value={String(graph.hidden + graph.added)} note={`${graph.hidden} ẩn · ${graph.added} thêm`} />
        <Stat
          label="Trả lời tự động từ mở rộng · From expansion"
          value={percent(graph.expansion_share)}
          note={`${graph.auto_replies_from_expansion}/${graph.auto_replies} trả lời tự động trong kỳ`}
        />
      </div>
    </section>
  );
}

// ── CSAT (17-1916) ──

function CsatCard({ title, line }: { title: string; line: CsatLineOut }) {
  const max = Math.max(1, ...Object.values(line.distribution));
  return (
    <section className="card p-4">
      <h2 className="text-sm font-medium">{title}</h2>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{num(line.mean, 2)}</p>
      <p className="text-xs text-[var(--text-muted)]">
        {line.ratings} đánh giá · tỷ lệ phản hồi {percent(line.response_rate)} ({line.ratings}/{line.resolved})
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
  );
}

export function CsatReport({ user }: { user: CurrentUser }) {
  const [month, setMonth] = useState(thisMonth());
  const [team, setTeam] = useState("");
  const q = query({ month, team });
  const { data, error } = useReport<CsatReportOut>(`/api/reports/csat${q}`);
  return (
    <>
      <Header title="Mức hài lòng · CSAT" note="Trả lời tự động và nhân viên xử lý là hai dịch vụ khác nhau: luôn báo cáo riêng (BR-F10-08).">
        <MonthPicker value={month} onChange={setMonth} />
        <TeamPicker user={user} value={team} onChange={setTeam} allowAll />
        <ExportButton path={`/api/reports/csat.csv${q}`} filename={`csat-${month}.csv`} />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <CsatCard title="Nhân viên xử lý · Handled by a person" line={data.person} />
            <CsatCard title="Trả lời tự động · Auto-replied" line={data.auto} />
          </div>
          {data.by_team.length > 0 && (
            <div className="mb-4">
              <Table head={["Nhóm", "Nhân viên", "Tự động", "Đánh giá"]}>
                {data.by_team.map((t) => (
                  <tr key={t.team}>
                    <td>{t.team}</td>
                    <td>{num(t.person.mean, 2)}</td>
                    <td>{num(t.auto.mean, 2)}</td>
                    <td>{t.person.ratings + t.auto.ratings}</td>
                  </tr>
                ))}
              </Table>
            </div>
          )}
          <section className="card p-4">
            <h2 className="mb-2 text-sm font-medium">Đánh giá thấp · Low ratings (đã che PII)</h2>
            {data.low_rated.length === 0 ? (
              <p className="text-xs text-[var(--text-muted)]">Không có.</p>
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {data.low_rated.map((r) => (
                  <li key={`${r.ticket_public_id}-${r.rated_at}`}>
                    <span className="font-mono text-xs">{r.ticket_public_id}</span> · {r.score}★ · {r.team ?? "—"}
                    <p className="text-[var(--text-muted)]">{r.comment}</p>
                  </li>
                ))}
              </ul>
            )}
          </section>
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
      <Header title="Sẵn sàng triển khai · Rollout readiness" note="Cùng số liệu mà cổng F9 đọc (BR-F10-10).">
        <ExportButton path="/api/reports/rollout.csv" filename="rollout.csv" />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-2">
            <Stat label="Tự động hoá (thực tế) · Automation live" value={percent(data.automation.live_rate)} note="đã thực hiện · không phải mục tiêu (BR-F10-09)" />
            <Stat label="Tự động hoá (nếu bật) · would-have" value={percent(data.automation.would_have_rate)} note="gồm quyết định shadow · không phải mục tiêu" />
          </div>
          <Table head={["Nhánh · Branch", "Đang bật", "Đồng thuận", "Đã duyệt", "Phủ", "Cổng đạt"]}>
            {data.branches.map((b) => (
              <tr key={b.branch}>
                <td className="font-mono">{b.branch}</td>
                <td>{b.live ? "live" : "shadow"}</td>
                <td>{percent(b.agreement.rate)}</td>
                <td>
                  {b.agreement.agreed}/{b.agreement.decided}
                </td>
                <td>{percent(b.coverage)}</td>
                <td>
                  {b.gates.filter((g) => g.met).length}/{b.gates.length}
                </td>
              </tr>
            ))}
          </Table>
          <p className="mt-3 text-xs text-[var(--text-muted)]">{data.days} ngày gần nhất.</p>
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
      <Header title="Bảo mật · Security" note="Quản lý chỉ thấy số đếm theo loại; chi tiết chỉ dành cho security (BR-F8-01).">
        <MonthPicker value={month} onChange={setMonth} />
        <ExportButton path={`/api/reports/security.csv?month=${month}`} filename={`security-${month}.csv`} />
      </Header>
      <Failed error={error} />
      {data && (
        <>
          <div className="mb-4 grid grid-cols-1 gap-3 md:grid-cols-4">
            <Stat label="Cảnh báo · Alerts" value={String(data.total)} />
            {data.detail && (
              <>
                <Stat label="Xác nhận p50 · Ack p50" value={duration(data.ack_p50_sec)} note={`p90 ${duration(data.ack_p90_sec)}`} />
                <Stat label="Xác nhận đúng hạn · Ack in target (K12)" value={`${data.ack_in_target ?? 0}/${data.acknowledged ?? 0}`} />
                <Stat label="Báo nhầm · False positive" value={percent(data.false_positive_rate)} note={`${data.false_positive ?? 0}/${data.closed ?? 0} đã đóng`} />
              </>
            )}
          </div>
          <Table head={["Loại · Kind", "Số lượng", "Đang mở"]}>
            {data.by_kind.map((k) => (
              <tr key={k.kind}>
                <td className="font-mono">{k.kind}</td>
                <td>{k.count}</td>
                <td>{k.open}</td>
              </tr>
            ))}
          </Table>
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
      <Header title="Sự cố diện rộng · Incidents" note="Thời gian xác nhận, đến thông báo đầu tiên (K13), và tỷ lệ gỡ liên kết (độ chính xác của bộ phát hiện).">
        <MonthPicker value={month} onChange={setMonth} />
        <ExportButton path={`/api/reports/incidents.csv?month=${month}`} filename={`incidents-${month}.csv`} />
      </Header>
      <Failed error={error} />
      {data && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <Stat label="Phát hiện · Detected" value={String(data.detected)} note={`${data.confirmed} xác nhận · ${data.dismissed} bỏ qua`} />
          <Stat label="Phiếu gắn sự cố · Linked tickets" value={String(data.linked_tickets)} />
          <Stat label="Xác nhận (trung vị) · Time to confirm" value={duration(data.confirm_p50_sec)} />
          <Stat label="Đến thông báo đầu · First broadcast" value={duration(data.first_broadcast_p50_sec)} note={`p90 ${duration(data.first_broadcast_p90_sec)} · mục tiêu ≤ 15 phút`} />
          <Stat label="Tỷ lệ gỡ liên kết · Unlink rate" value={percent(data.unlink_rate)} note={`${data.links_unlinked}/${data.links_created} liên kết`} />
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
      <Header title="Thông báo · Notifications" note="Độ trễ p95 từ khi tạo đến khi gửi, và số lần thất bại theo kênh (K8).">
        <Field label="Số ngày · Days">
          <select className="field w-28" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            {[1, 7, 30].map((d) => (
              <option key={d}>{d}</option>
            ))}
          </select>
        </Field>
        <ExportButton path={`/api/reports/notifications.csv?days=${days}`} filename="notifications.csv" />
      </Header>
      <Failed error={error} />
      {data && (
        <Table head={["Kênh · Channel", "Tin", "Đã gửi", "Thất bại", "Độ trễ p95"]}>
          {data.channels.map((c) => (
            <tr key={c.channel}>
              <td className="font-mono">{c.channel}</td>
              <td>{c.messages}</td>
              <td>{c.delivered}</td>
              <td className={c.failed ? "text-[var(--danger)]" : ""}>{c.failed}</td>
              <td>{duration(c.latency_p95_sec)}</td>
            </tr>
          ))}
        </Table>
      )}
    </>
  );
}
