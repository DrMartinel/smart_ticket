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
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";

const CATEGORIES = ["network", "access", "hardware", "software", "security", "other"];

function Stat({ label, value, note, tone }: { label: string; value: string; note?: string; tone?: string }) {
  return (
    <Card className="px-4 py-3">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold">{value}</p>
      {note && <p className={`text-xs ${tone ?? "text-muted-foreground"}`}>{note}</p>}
    </Card>
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
  if (!incident) return <p className="text-sm text-muted-foreground">{error ?? "Đang tải…"}</p>;

  const latest: BroadcastOut | undefined = incident.broadcasts[0];
  const det = incident.detector as Record<string, number>;
  const canBroadcast = isManager && (incident.status === "confirmed" || incident.status === "resolved");

  return (
    <div className="mx-auto flex max-w-[1180px] flex-col gap-5">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs text-muted-foreground">
            <Link href="/incidents" className="hover:underline">
              Sự cố
            </Link>{" "}
            / {incident.public_id}
          </p>
          <h1 className="text-xl font-semibold">
            {incident.public_id} · {incident.title}
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
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
                <Button variant="outline" onClick={() => setDialog("dismiss")}>
                  Không phải sự cố
                </Button>
                <Button onClick={() => setDialog("confirm")}>
                  Xác nhận…
                </Button>
              </>
            )}
            {incident.status === "confirmed" && (
              <Button onClick={() => setDialog("resolve")}>
                Đã khắc phục…
              </Button>
            )}
            {incident.status === "resolved" && (
              <Button variant="outline" onClick={() => setDialog("reopen")}>
                Mở lại
              </Button>
            )}
          </div>
        )}
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}
      {result && (
        <Card className="px-4 py-3 text-sm">
          Đã đóng {result.closed.length} phiếu
          {result.failed.length > 0 && (
            <>
              {" · "}
              <span className="text-danger">{result.failed.length} không đóng được:</span>{" "}
              {result.failed.map((f) => `${f.ticket} (${f.code})`).join(", ")} — người được giao (nếu có) đã được báo.
            </>
          )}
        </Card>
      )}
      {incident.dismiss_reason && (
        <p className="text-sm text-muted-foreground">Bỏ qua: {incident.dismiss_reason}</p>
      )}
      {incident.resolution_note_masked && (
        <p className="text-sm">
          <span className="text-muted-foreground">Ghi chú khắc phục:</span> {incident.resolution_note_masked}
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
          tone={incident.target_breached ? "text-danger" : "text-warn"}
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
        <Card asChild>
          <section className="flex flex-col gap-3 px-4 py-4">
            <h2 className="text-sm font-semibold">Gửi cập nhật · Broadcast an update</h2>
            <div className="flex flex-wrap gap-3 text-sm">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Stage</span>
                <NativeSelect value={stage} onChange={(e) => setStage(e.target.value)}>
                  {STAGES.filter((s) => s !== "resolved").map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </NativeSelect>
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">ETA (+07)</span>
                <Input
                  type="datetime-local"
                  value={etaAt}
                  disabled={etaUnknown}
                  onChange={(e) => setEtaAt(e.target.value)}
                />
              </label>
              <label className="flex items-center gap-2 self-end pb-2 text-sm">
                <Checkbox checked={etaUnknown} onCheckedChange={(checked) => setEtaUnknown(checked === true)} />
                chưa xác định
              </label>
            </div>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted-foreground">Nội dung (vi)</span>
              <Textarea className="min-h-16" value={bodyVi} onChange={(e) => setBodyVi(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted-foreground">Message (en, optional)</span>
              <Textarea className="min-h-12" value={bodyEn} onChange={(e) => setBodyEn(e.target.value)} />
            </label>
            <div className="flex items-center justify-between gap-4">
              <p className="text-xs text-muted-foreground">
                Gửi một lần tới mỗi người trong {incident.requesters} người yêu cầu, in-app + email, bắt buộc (BR-F7-05); thêm bình luận công khai trên mỗi phiếu liên quan.
              </p>
              <Button
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
              </Button>
            </div>
          </section>
        </Card>
      )}

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Lịch sử cập nhật · Broadcast history</h2>
        <Card className="overflow-x-auto">
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead>Time</TableHead>
                <TableHead>Stage</TableHead>
                <TableHead>Message</TableHead>
                <TableHead>ETA</TableHead>
                <TableHead>Delivered</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {incident.broadcasts.map((b) => (
                <TableRow key={b.id}>
                  <TableCell>{vnTime(b.sent_at)}</TableCell>
                  <TableCell>
                    <StageChip stage={b.stage} />
                  </TableCell>
                  <TableCell>
                    {b.body_vi_masked}
                    {b.body_en_masked && <div className="text-xs text-muted-foreground">{b.body_en_masked}</div>}
                  </TableCell>
                  <TableCell>{eta(b.eta, b.eta_unknown)}</TableCell>
                  <TableCell>
                    {b.delivery.in_app_delivered} / {b.delivery.email_delivered} email
                    {b.delivery.email_failed > 0 && <span className="text-danger"> · {b.delivery.email_failed} failed</span>}
                  </TableCell>
                </TableRow>
              ))}
              {incident.broadcasts.length === 0 && (
                <TableRow>
                  <TableCell colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                    Chưa có cập nhật nào.
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </Card>
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Phiếu liên quan · Linked tickets ({incident.links.length})</h2>
        <Card className="overflow-x-auto">
          <Table className="min-w-[760px]">
            <TableHeader>
              <TableRow>
                <TableHead>Ticket</TableHead>
                <TableHead>Subject (masked)</TableHead>
                <TableHead>Requester</TableHead>
                <TableHead>Linked</TableHead>
                <TableHead>Clock</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {incident.links.map((l) => (
                <TableRow key={l.ticket}>
                  <TableCell>
                    <Link href={`/tickets/${l.ticket}`} className="text-primary hover:underline">
                      {l.ticket}
                    </Link>
                  </TableCell>
                  <TableCell>{l.subject_masked}</TableCell>
                  <TableCell>{l.requester}</TableCell>
                  <TableCell>
                    {vnTime(l.linked_at)}
                    <span className="text-xs text-muted-foreground">
                      {" "}
                      · {l.linked_by}
                      {l.similarity !== null && ` ${l.similarity.toFixed(2)}`}
                    </span>
                  </TableCell>
                  <TableCell>
                    {l.clock_state === "paused" ? (
                      <Badge variant="neutral" className="bg-muted">Tạm dừng · Paused</Badge>
                    ) : (
                      <Badge variant="neutral">{l.clock_state ?? "—"}</Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    {(isManager || l.assigned_to === user.username) && incident.status !== "closed" && (
                      <Button variant="link" size="inline"  onClick={() => setUnlinking(l.ticket)}>
                        Gỡ liên kết
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      </section>

      <Modal
        open={dialog === "confirm"}
        title="Xác nhận sự cố"
        subtitle="Mỗi phiếu liên quan đang chờ duyệt được duyệt 'approve' dưới tên bạn; đồng hồ xử lý tạm dừng (BR-F7-03, 07)."
        onClose={() => setDialog(null)}
        footer={
          <Button
            disabled={busy || title.trim().length < 3}
            onClick={() => act(() => api.post(`/api/incidents/${incident.public_id}/confirm`, { title, category, service }))}
          >
            Xác nhận
          </Button>
        }
      >
        <div className="flex flex-col gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Tên sự cố</span>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Category</span>
            <NativeSelect value={category} onChange={(e) => setCategory(e.target.value)}>
              {CATEGORIES.map((c) => (
                <option key={c}>{c}</option>
              ))}
            </NativeSelect>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Dịch vụ bị ảnh hưởng</span>
            <Input value={service} onChange={(e) => setService(e.target.value)} />
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
          <Button
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
          </Button>
        }
      >
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-xs text-muted-foreground">Lý do</span>
          <Textarea className="min-h-16" value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
      </Modal>

      <Modal
        open={dialog === "resolve"}
        title="Đã khắc phục sự cố"
        subtitle="Gửi cập nhật cuối (stage resolved) tới mọi người yêu cầu."
        onClose={() => setDialog(null)}
        footer={
          <Button
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
          </Button>
        }
      >
        <div className="flex flex-col gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Ghi chú khắc phục (công khai)</span>
            <Textarea className="min-h-20" value={reason} onChange={(e) => setReason(e.target.value)} />
          </label>
          <label className="flex items-center gap-2">
            <Checkbox checked={closeAll} onCheckedChange={(checked) => setCloseAll(checked === true)} />
            Đóng tất cả phiếu liên quan ({incident.links.length})
          </label>
          <p className="text-xs text-muted-foreground">
            {closeAll
              ? "Mỗi phiếu được chuyển sang resolved theo quy trình của nó; phiếu bị từ chối được liệt kê và người được giao được báo (BR-F7-06)."
              : "Các phiếu vẫn mở; đồng hồ xử lý chạy lại."}
          </p>
        </div>
      </Modal>
    </div>
  );
}
