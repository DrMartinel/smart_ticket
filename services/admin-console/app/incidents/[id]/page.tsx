"use client";

// One incident (F7 · Incident page 14-1090): confirm or dismiss a proposal, broadcast updates with
// an ETA, resolve with close-all (Resolve dialog 14-1324), unlink a wrongly matched ticket.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { IncidentStatusChip, STAGES, StageChip, eta, fromLocal } from "@/components/incidents/chips";
import { vnTime } from "@/components/security/badges";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { BroadcastOut, CloseResultOut, IncidentDetailOut } from "@/lib/types/generated";

const CATEGORIES = ["network", "access", "hardware", "software", "security", "other"];

function Stat({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: string }) {
  return (
    <div className="card px-4 py-3">
      <p className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
      {note && <p className={`text-xs ${tone ?? "text-[var(--text-muted)]"}`}>{note}</p>}
    </div>
  );
}

function remaining(target: string): string {
  const minutes = Math.round((new Date(target).getTime() - Date.now()) / 60000);
  if (minutes < 0) return "Quá hạn";
  return `Còn ${Math.floor(minutes / 60)}g ${String(minutes % 60).padStart(2, "0")}p`;
}

export default function IncidentPage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const [incident, setIncident] = useState<IncidentDetailOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dialog, setDialog] = useState<"confirm" | "dismiss" | "resolve" | "reopen" | null>(null);
  const [unlinking, setUnlinking] = useState<string | null>(null);
  const [result, setResult] = useState<CloseResultOut | null>(null);

  // Confirm
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("network");
  const [service, setService] = useState("");
  // Dismiss, reopen, unlink, resolve
  const [reason, setReason] = useState("");
  const [closeAll, setCloseAll] = useState(true);
  // Broadcast
  const [stage, setStage] = useState("investigating");
  const [bodyVi, setBodyVi] = useState("");
  const [bodyEn, setBodyEn] = useState("");
  const [etaAt, setEtaAt] = useState("");
  const [etaUnknown, setEtaUnknown] = useState(false);

  const isManager = user?.capabilities?.includes("incident_manager") ?? false;

  const load = useCallback(() => {
    api
      .get<IncidentDetailOut>(`/api/incidents/${id}`)
      .then((i) => {
        setIncident(i);
        setTitle((t) => t || i.title.replace(/^Proposed: /, ""));
        setStage((s) => (i.stage && i.stage !== "resolved" ? i.stage : s));
        setError(null);
      })
      .catch((e) => setError(e instanceof ApiError && e.status === 404 ? "Không có sự cố này." : "Không tải được sự cố."));
  }, [id]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  async function act(run: () => Promise<unknown>) {
    setBusy(true);
    try {
      await run();
      setDialog(null);
      setUnlinking(null);
      setReason("");
      load();
    } catch (e) {
      setError(e instanceof ApiError ? `${e.code ?? e.status}: ${e.message}` : "Không thực hiện được.");
    } finally {
      setBusy(false);
    }
  }

  if (!user) return null;
  if (!incident) return <p className="text-sm text-[var(--text-muted)]">{error ?? "Đang tải…"}</p>;

  const latest: BroadcastOut | undefined = incident.broadcasts[0];
  const det = incident.detector as Record<string, number>;
  const canBroadcast = isManager && (incident.status === "confirmed" || incident.status === "resolved");

  return (
    <div className="mx-auto flex max-w-[1180px] flex-col gap-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs text-[var(--text-muted)]">
            <Link href="/incidents" className="hover:underline">
              Sự cố
            </Link>{" "}
            / {incident.public_id}
          </p>
          <h1 className="text-xl font-semibold">
            {incident.public_id} · {incident.title}
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-[var(--text-muted)]">
            <IncidentStatusChip status={incident.status} />
            {incident.category ?? "category chưa chọn"}
            {incident.service && ` · service ${incident.service}`}
            {incident.confirmed_at && ` · confirmed ${vnTime(incident.confirmed_at)} by ${incident.confirmed_by}`}
            {incident.status !== "proposed" && (
              <>
                {" · stage "}
                <StageChip stage={incident.stage} />
              </>
            )}
          </p>
        </div>
        {isManager && (
          <div className="flex gap-2">
            {incident.status === "proposed" && (
              <>
                <button className="btn btn-secondary" onClick={() => setDialog("dismiss")}>
                  Không phải sự cố
                </button>
                <button className="btn btn-primary" onClick={() => setDialog("confirm")}>
                  Xác nhận…
                </button>
              </>
            )}
            {incident.status === "confirmed" && (
              <button className="btn btn-primary" onClick={() => setDialog("resolve")}>
                Đã khắc phục…
              </button>
            )}
            {incident.status === "resolved" && (
              <button className="btn btn-secondary" onClick={() => setDialog("reopen")}>
                Mở lại
              </button>
            )}
          </div>
        )}
      </header>

      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
      {result && (
        <div className="card px-4 py-3 text-sm">
          Đã đóng {result.closed.length} phiếu
          {result.failed.length > 0 && (
            <>
              {" · "}
              <span className="text-[var(--danger)]">{result.failed.length} không đóng được:</span>{" "}
              {result.failed.map((f) => `${f.ticket} (${f.code})`).join(", ")} — người được giao (nếu có) đã được báo.
            </>
          )}
        </div>
      )}
      {incident.dismiss_reason && (
        <p className="text-sm text-[var(--text-muted)]">Bỏ qua: {incident.dismiss_reason}</p>
      )}
      {incident.resolution_note_masked && (
        <p className="text-sm">
          <span className="text-[var(--text-muted)]">Ghi chú khắc phục:</span> {incident.resolution_note_masked}
        </p>
      )}

      <section className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Linked tickets" value={String(incident.ticket_count)} note={`from ${incident.requesters} requesters`} />
        <Stat
          label="Detection"
          value={det.count !== undefined ? `${det.count} in ${det.window_minutes ?? "?"} min` : incident.detected_by}
          note={det.count !== undefined ? `baseline ${Number(det.baseline).toFixed(2)} · σ ${Number(det.sigma).toFixed(2)} · min_count ${det.min_count ?? "?"}` : "declared by hand"}
        />
        <Stat
          label="Incident SLA"
          value={incident.target_resolve_at ? remaining(incident.target_resolve_at) : "—"}
          note={incident.target_resolve_at ? `due ${vnTime(incident.target_resolve_at)} (+07), 24×7` : "starts at confirm"}
          tone={incident.target_breached ? "text-[var(--danger)]" : "text-[var(--warn)]"}
        />
        <Stat
          label="Last broadcast"
          value={latest ? vnTime(latest.sent_at) : "—"}
          note={
            latest
              ? `${latest.delivery.in_app_delivered} in-app · ${latest.delivery.email_delivered} email · ${latest.delivery.email_failed} email failed`
              : "none yet"
          }
        />
      </section>

      {canBroadcast && (
        <section className="card flex flex-col gap-3 px-4 py-4">
          <h2 className="text-sm font-semibold">Gửi cập nhật · Broadcast an update</h2>
          <div className="flex flex-wrap gap-3 text-sm">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--text-muted)]">Stage</span>
              <select className="field" value={stage} onChange={(e) => setStage(e.target.value)}>
                {STAGES.filter((s) => s !== "resolved").map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--text-muted)]">ETA (+07)</span>
              <input
                type="datetime-local"
                className="field"
                value={etaAt}
                disabled={etaUnknown}
                onChange={(e) => setEtaAt(e.target.value)}
              />
            </label>
            <label className="flex items-center gap-2 self-end pb-2 text-sm">
              <input type="checkbox" checked={etaUnknown} onChange={(e) => setEtaUnknown(e.target.checked)} />
              chưa xác định
            </label>
          </div>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-[var(--text-muted)]">Nội dung (vi)</span>
            <textarea className="field min-h-16" value={bodyVi} onChange={(e) => setBodyVi(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-[var(--text-muted)]">Message (en, optional)</span>
            <textarea className="field min-h-12" value={bodyEn} onChange={(e) => setBodyEn(e.target.value)} />
          </label>
          <div className="flex items-center justify-between gap-4">
            <p className="text-xs text-[var(--text-muted)]">
              Gửi một lần tới mỗi người trong {incident.requesters} người yêu cầu, in-app + email, bắt buộc (BR-F7-05); thêm bình luận công khai trên mỗi phiếu liên quan.
            </p>
            <button
              className="btn btn-primary"
              disabled={busy || !bodyVi.trim()}
              onClick={() =>
                act(async () => {
                  await api.post(`/api/incidents/${incident.public_id}/broadcasts`, {
                    stage,
                    body_vi: bodyVi,
                    body_en: bodyEn,
                    eta: etaUnknown ? null : fromLocal(etaAt),
                    eta_unknown: etaUnknown,
                  });
                  setBodyVi("");
                  setBodyEn("");
                })
              }
            >
              Gửi cập nhật
            </button>
          </div>
        </section>
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Lịch sử cập nhật · Broadcast history</h2>
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-2.5 font-medium">Time</th>
                <th className="px-4 py-2.5 font-medium">Stage</th>
                <th className="px-4 py-2.5 font-medium">Message</th>
                <th className="px-4 py-2.5 font-medium">ETA</th>
                <th className="px-4 py-2.5 font-medium">Delivered</th>
              </tr>
            </thead>
            <tbody>
              {incident.broadcasts.map((b) => (
                <tr key={b.id} className="border-t border-[var(--border)]">
                  <td className="px-4 py-2.5">{vnTime(b.sent_at)}</td>
                  <td className="px-4 py-2.5">
                    <StageChip stage={b.stage} />
                  </td>
                  <td className="px-4 py-2.5">
                    {b.body_vi_masked}
                    {b.body_en_masked && <div className="text-xs text-[var(--text-muted)]">{b.body_en_masked}</div>}
                  </td>
                  <td className="px-4 py-2.5">{eta(b.eta, b.eta_unknown)}</td>
                  <td className="px-4 py-2.5">
                    {b.delivery.in_app_delivered} / {b.delivery.email_delivered} email
                    {b.delivery.email_failed > 0 && <span className="text-[var(--danger)]"> · {b.delivery.email_failed} failed</span>}
                  </td>
                </tr>
              ))}
              {incident.broadcasts.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-4 py-6 text-center text-[var(--text-muted)]">
                    Chưa có cập nhật nào.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Phiếu liên quan · Linked tickets ({incident.links.length})</h2>
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[760px] text-left text-sm">
            <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-2.5 font-medium">Ticket</th>
                <th className="px-4 py-2.5 font-medium">Subject (masked)</th>
                <th className="px-4 py-2.5 font-medium">Requester</th>
                <th className="px-4 py-2.5 font-medium">Linked</th>
                <th className="px-4 py-2.5 font-medium">Clock</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {incident.links.map((l) => (
                <tr key={l.ticket} className="border-t border-[var(--border)]">
                  <td className="px-4 py-2.5">
                    <Link href={`/tickets/${l.ticket}`} className="text-[var(--accent)] hover:underline">
                      {l.ticket}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5">{l.subject_masked}</td>
                  <td className="px-4 py-2.5">{l.requester}</td>
                  <td className="px-4 py-2.5">
                    {vnTime(l.linked_at)}
                    <span className="text-xs text-[var(--text-muted)]">
                      {" "}
                      · {l.linked_by}
                      {l.similarity !== null && ` ${l.similarity.toFixed(2)}`}
                    </span>
                  </td>
                  <td className="px-4 py-2.5">
                    {l.clock_state === "paused" ? (
                      <span className="badge bg-[var(--surface-2)]">Tạm dừng · Paused</span>
                    ) : (
                      <span className="badge">{l.clock_state ?? "—"}</span>
                    )}
                  </td>
                  <td className="px-4 py-2.5 text-right">
                    {(isManager || l.assigned_to === user.username) && incident.status !== "closed" && (
                      <button className="text-[var(--accent)] hover:underline" onClick={() => setUnlinking(l.ticket)}>
                        Gỡ liên kết
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Modal
        open={dialog === "confirm"}
        title="Xác nhận sự cố"
        subtitle="Mỗi phiếu liên quan đang chờ duyệt được duyệt 'approve' dưới tên bạn; đồng hồ xử lý tạm dừng (BR-F7-03, 07)."
        onClose={() => setDialog(null)}
        footer={
          <button
            className="btn btn-primary"
            disabled={busy || title.trim().length < 3}
            onClick={() => act(() => api.post(`/api/incidents/${incident.public_id}/confirm`, { title, category, service }))}
          >
            Xác nhận
          </button>
        }
      >
        <div className="flex flex-col gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Tên sự cố</span>
            <input className="field" value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Category</span>
            <select className="field" value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Dịch vụ bị ảnh hưởng</span>
            <input className="field" value={service} onChange={(e) => setService(e.target.value)} />
          </label>
        </div>
      </Modal>

      <Modal
        open={dialog === "dismiss" || dialog === "reopen" || unlinking !== null}
        title={dialog === "dismiss" ? "Không phải sự cố" : dialog === "reopen" ? "Mở lại sự cố" : `Gỡ ${unlinking} khỏi sự cố`}
        subtitle={
          dialog === "dismiss"
            ? "Các phiếu được gỡ liên kết và vẫn chờ duyệt như bình thường."
            : dialog === "reopen"
              ? "Đồng hồ của các phiếu còn mở lại tạm dừng."
              : "Phiếu về hàng chờ duyệt low_confidence; đồng hồ chạy lại."
        }
        onClose={() => {
          setDialog(null);
          setUnlinking(null);
        }}
        footer={
          <button
            className="btn btn-primary"
            disabled={busy || !reason.trim()}
            onClick={() =>
              act(() =>
                unlinking
                  ? api.delete(`/api/incidents/${incident.public_id}/links/${unlinking}`, { reason })
                  : api.post(`/api/incidents/${incident.public_id}/${dialog}`, { reason }),
              )
            }
          >
            Lưu
          </button>
        }
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-[var(--text-muted)]">Lý do</span>
          <textarea className="field min-h-16" value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      </Modal>

      <Modal
        open={dialog === "resolve"}
        title="Đã khắc phục sự cố"
        subtitle="Gửi cập nhật cuối (stage resolved) tới mọi người yêu cầu."
        onClose={() => setDialog(null)}
        footer={
          <button
            className="btn btn-primary"
            disabled={busy || !reason.trim()}
            onClick={() =>
              act(async () => {
                setResult(
                  await api.post<CloseResultOut>(`/api/incidents/${incident.public_id}/resolve`, {
                    resolution_note: reason,
                    close_all: closeAll,
                  }),
                );
              })
            }
          >
            Xác nhận đã khắc phục
          </button>
        }
      >
        <div className="flex flex-col gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Ghi chú khắc phục (công khai)</span>
            <textarea className="field min-h-20" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={closeAll} onChange={(e) => setCloseAll(e.target.checked)} />
            Đóng tất cả phiếu liên quan ({incident.links.length})
          </label>
          <p className="text-xs text-[var(--text-muted)]">
            {closeAll
              ? "Mỗi phiếu được chuyển sang resolved theo quy trình của nó; phiếu bị từ chối được liệt kê và người được giao được báo (BR-F7-06)."
              : "Các phiếu vẫn mở; đồng hồ xử lý chạy lại."}
          </p>
        </div>
      </Modal>
    </div>
  );
}
