"use client";

// A KB page's entity graph (F11 UC-F11-01..03): its pointers, editors' corrections and rebuilds.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { KbTabs, canEditKb } from "@/components/kb/KbTabs";
import { api, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";
import type { GraphEdgeOut, PageGraphOut, RebuildRequestOut } from "@/lib/types/generated";

const REBUILD_STATE_VI: Record<string, string> = {
  pending: "Đang chờ",
  done: "Xong",
  failed: "Lỗi",
};

type Correction = { target: string; action: "hide" | "add" | "remove" } | null;

function Build({ label, request }: { label: string; request: RebuildRequestOut | null }) {
  return (
    <div className="card p-4 text-sm">
      <p className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">{label}</p>
      {request ? (
        <>
          <p className="mt-1 font-medium">
            {REBUILD_STATE_VI[request.state] ?? request.state} · {request.reason === "manual" ? "yêu cầu tay" : "sau xuất bản"}
          </p>
          <p className="text-xs text-[var(--text-muted)]">
            {dateTime(request.done_at ?? request.requested_at)}
            {request.build_id && <span className="block truncate font-mono">{request.build_id}</span>}
          </p>
        </>
      ) : (
        <p className="mt-1 text-[var(--text-muted)]">—</p>
      )}
    </div>
  );
}

function EdgeTable({
  title,
  edges,
  editor,
  outgoing,
  onCorrect,
  onConfirm,
}: {
  title: string;
  edges: GraphEdgeOut[];
  editor: boolean;
  outgoing: boolean;
  onCorrect: (c: Correction) => void;
  onConfirm: (target: string) => void;
}) {
  return (
    <section className="card mb-5 overflow-x-auto">
      <h2 className="border-b border-[var(--border)] px-4 py-3 text-sm font-semibold">
        {title} <span className="font-normal text-[var(--text-muted)]">({edges.length})</span>
      </h2>
      {edges.length === 0 ? (
        <p className="px-4 py-6 text-center text-sm text-[var(--text-muted)]">Chưa có liên kết.</p>
      ) : (
        <table className="w-full min-w-[640px] table-fixed text-sm">
          <thead className="bg-[var(--surface-2)] text-left text-xs text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2.5 font-medium">Trang · Page</th>
              <th className="w-16 px-4 py-2.5 text-right font-medium">Điểm</th>
              <th className="px-4 py-2.5 font-medium">Bằng chứng · Evidence</th>
              <th className="w-36 px-4 py-2.5 font-medium">Trạng thái</th>
              {editor && outgoing && <th className="w-28 px-4 py-2.5" />}
            </tr>
          </thead>
          <tbody>
            {edges.map((e) => (
              <tr key={e.slug} className="border-t border-[var(--border)] align-top">
                <td className="px-4 py-3">
                  <Link href={`/kb/graph/${encodeURIComponent(e.slug)}`} className="block truncate font-medium hover:text-[var(--accent)]">
                    {e.title}
                  </Link>
                  <span className="block truncate font-mono text-xs text-[var(--text-muted)]">{e.slug}</span>
                </td>
                <td className="px-4 py-3 text-right font-mono tabular-nums">{e.score ?? "—"}</td>
                <td className="px-4 py-3 text-xs">
                  {e.evidence.length > 0 ? (
                    <>
                      <span className="line-clamp-2">{e.evidence[0]}</span>
                      {e.evidence.length > 1 && <span className="text-[var(--text-muted)]">+{e.evidence.length - 1} cặp khác</span>}
                    </>
                  ) : (
                    <span className="text-[var(--text-muted)]">Do biên tập viên thêm</span>
                  )}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-wrap gap-1">
                    {e.stale && <span className="badge tone-warn">Cũ · stale</span>}
                    {e.reviewed && <span className="badge tone-ok">Đã xác nhận</span>}
                    {e.override?.action === "hide" && <span className="badge tone-danger">Ẩn</span>}
                    {e.override?.action === "add" && <span className="badge tone-info">Thêm tay</span>}
                  </div>
                  {e.override && (
                    <p className="mt-1 text-xs text-[var(--text-muted)]">
                      “{e.override.reason}” · {e.override.created_by}
                    </p>
                  )}
                </td>
                {editor && outgoing && (
                  <td className="px-4 py-3 text-right">
                    <span className="inline-flex flex-wrap justify-end gap-2 text-xs">
                      {e.score !== null && !e.reviewed && !e.override && (
                        <button className="text-[var(--accent)] hover:underline" onClick={() => onConfirm(e.slug)}>
                          Xác nhận
                        </button>
                      )}
                      {!e.override && (
                        <button className="text-[var(--danger)] hover:underline" onClick={() => onCorrect({ target: e.slug, action: "hide" })}>
                          Ẩn
                        </button>
                      )}
                      {e.override && (
                        <button className="text-[var(--accent)] hover:underline" onClick={() => onCorrect({ target: e.slug, action: "remove" })}>
                          Bỏ điều chỉnh
                        </button>
                      )}
                    </span>
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default function PageGraphPage() {
  const user = useRequireAuth();
  const { slug } = useParams<{ slug: string }>();
  const page = decodeURIComponent(slug);
  const [graph, setGraph] = useState<PageGraphOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [correction, setCorrection] = useState<Correction>(null);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .get<PageGraphOut>(`/api/kb/${encodeURIComponent(page)}/graph`)
      .then(setGraph)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Không tải được đồ thị."));
  }, [page]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  if (!user) return null;
  const editor = (user.capabilities ?? []).includes("kb_editor");

  const run = async (call: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await call();
      setCorrection(null);
      setTarget("");
      setReason("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code ?? err.status}: ${err.message}` : "Không lưu được.");
    } finally {
      setBusy(false);
    }
  };

  const base = `/api/kb/${encodeURIComponent(page)}/graph`;
  const submit = () => {
    if (!correction) return;
    if (correction.action === "remove") {
      return run(() => api.delete(`${base}/overrides/${encodeURIComponent(correction.target)}`, { reason }));
    }
    return run(() => api.post(`${base}/overrides`, { target: correction.target || target.trim(), action: correction.action, reason }));
  };

  return (
    <div className="mx-auto max-w-[1280px]">
      <KbTabs user={user} />
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Đồ thị trang · Page graph</h1>
          <p className="font-mono text-xs text-[var(--text-muted)]">{page}</p>
          <p className="mt-1 max-w-[720px] text-xs text-[var(--text-muted)]">
            Liên kết mở rộng tìm kiếm theo đến trang chứa cách khắc phục. Điểm chỉ dùng để xếp thứ tự, không bao giờ quyết định trả lời tự động.
          </p>
        </div>
        <div className="flex gap-2">
          {editor && (
            <button className="btn btn-secondary" onClick={() => setCorrection({ target: "", action: "add" })}>
              Thêm liên kết
            </button>
          )}
          {canEditKb(user) && (
            <button
              className="btn btn-primary"
              disabled={busy || Boolean(graph?.pending_request)}
              onClick={() => void run(() => api.post(`${base}/rebuild`))}
            >
              Dựng lại · Rebuild
            </button>
          )}
        </div>
      </header>

      {error && <p className="tone-danger mb-3 rounded-[5px] px-3 py-2 text-sm">{error}</p>}

      {correction && (
        <form
          className="card mb-5 flex flex-wrap items-end gap-2 p-4 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <p className="w-full font-medium">
            {correction.action === "hide" && `Ẩn liên kết đến ${correction.target}`}
            {correction.action === "remove" && `Bỏ điều chỉnh với ${correction.target}`}
            {correction.action === "add" && "Thêm liên kết đến một trang (xếp đầu khi mở rộng)"}
          </p>
          {correction.action === "add" && (
            <input className="field w-80 font-mono" placeholder="slug trang đích" value={target} onChange={(e) => setTarget(e.target.value)} required autoFocus />
          )}
          <input
            className="field min-w-[280px] flex-1"
            placeholder="Lý do (bắt buộc, được ghi nhật ký)"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            required
            autoFocus={correction.action !== "add"}
          />
          <button type="submit" className="btn btn-primary" disabled={busy}>
            Lưu
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => setCorrection(null)}>
            Huỷ
          </button>
        </form>
      )}

      {graph === null && !error && <p className="text-sm text-[var(--text-muted)]">Loading…</p>}
      {graph && (
        <>
          <div className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-2">
            <Build label="Lần dựng gần nhất · Last build" request={graph.last_build} />
            <Build label="Yêu cầu đang chờ · Pending" request={graph.pending_request} />
          </div>
          <EdgeTable
            title="Trỏ đến · Outgoing"
            edges={graph.outgoing}
            editor={editor}
            outgoing
            onCorrect={setCorrection}
            onConfirm={(t) => void run(() => api.post(`${base}/edges/${encodeURIComponent(t)}/confirm`))}
          />
          <EdgeTable
            title="Được trỏ từ · Incoming"
            edges={graph.incoming}
            editor={editor}
            outgoing={false}
            onCorrect={setCorrection}
            onConfirm={() => undefined}
          />
        </>
      )}
    </div>
  );
}
