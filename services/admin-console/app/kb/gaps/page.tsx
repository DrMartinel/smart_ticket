"use client";

// The weekly KB-gap report (F6 · KB gaps 13-1299): refused tickets by topic, each a gap (no page)
// or an update (a page that doesn't answer them).

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { KbTabs } from "@/components/kb/KbTabs";
import { vnTime } from "@/components/security/badges";
import { api, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { GapReportOut } from "@/lib/types/generated";

const SAMPLES = 3;

export default function GapsPage() {
  const user = useRequireAuth();
  const [report, setReport] = useState<GapReportOut | null>(null);
  const [dismissing, setDismissing] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<GapReportOut>("/api/kb/gaps")
      .then(setReport)
      .catch(() => setError("Không tải được báo cáo."));
  }, []);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  if (!user) return null;

  const dismiss = async (id: string) => {
    setError(null);
    try {
      await api.post(`/api/kb/gaps/${id}/dismiss`, { reason });
      setDismissing(null);
      setReason("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code ?? err.status}: ${err.message}` : "Không ẩn được cụm.");
    }
  };

  return (
    <div className="mx-auto max-w-[1180px]">
      <KbTabs user={user} />
      <header className="mb-4">
        <h1 className="text-xl font-semibold">
          Thiếu KB · KB gaps
          {report?.window_start && report.window_end && (
            <span className="ml-2 text-sm font-normal text-[var(--text-muted)]">
              {vnTime(report.window_start)} – {vnTime(report.window_end)}
            </span>
          )}
        </h1>
        <p className="text-xs text-[var(--text-muted)]">
          Cụm phiếu bị từ chối (retrieval_below_floor) và phiếu người duyệt đánh dấu trang KB sai (BR-F6-07). Chỉ hiển thị tiêu
          đề đã che. {report ? `${report.tickets_considered} phiếu được xét.` : ""}
        </p>
      </header>

      {error && <p className="tone-danger mb-3 rounded-[5px] px-3 py-2 text-sm">{error}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2.5 font-medium">Tickets</th>
              <th className="px-4 py-2.5 font-medium">Sample subjects</th>
              <th className="px-4 py-2.5 font-medium">Nearest live page</th>
              <th className="px-4 py-2.5 font-medium">Similarity</th>
              <th className="px-4 py-2.5 font-medium">Label</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {report?.clusters.map((c) => (
              <tr key={c.id} className="border-t border-[var(--border)] align-top">
                <td className="px-4 py-2.5">{c.size}</td>
                <td className="px-4 py-2.5">
                  {c.tickets.slice(0, SAMPLES).map((t) => (
                    <div key={t.public_id} className="text-xs">
                      <Link href={`/tickets/${t.public_id}`} className="text-[var(--accent)]">
                        {t.public_id}
                      </Link>{" "}
                      · {t.subject_masked}
                    </div>
                  ))}
                  {c.tickets.length > SAMPLES && <div className="text-xs text-[var(--text-muted)]">+{c.tickets.length - SAMPLES} phiếu nữa</div>}
                </td>
                <td className="px-4 py-2.5 font-mono text-xs">{c.nearest_slug ?? "—"}</td>
                <td className="px-4 py-2.5">{c.nearest_similarity?.toFixed(2) ?? "—"}</td>
                <td className="px-4 py-2.5">
                  <span className={`badge ${c.label === "update" ? "tone-info" : "tone-warn"}`}>{c.label}</span>
                </td>
                <td className="px-4 py-2.5 text-right">
                  {c.draft_id ? (
                    <Link href={`/kb/drafts/${c.draft_id}`} className="text-[var(--accent)] hover:underline">
                      Xem bản nháp
                    </Link>
                  ) : dismissing === c.id ? (
                    <form
                      className="flex items-center gap-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void dismiss(c.id);
                      }}
                    >
                      <input className="field w-48" placeholder="ngoài phạm vi IT" value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
                      <button className="btn btn-secondary py-1 text-xs" type="submit">
                        Ẩn
                      </button>
                    </form>
                  ) : (
                    <div className="flex flex-col items-end gap-1">
                      <Link
                        className="btn btn-secondary py-1 text-xs"
                        href={
                          c.label === "update" && c.nearest_slug
                            ? `/kb/drafts/new?kind=edit&slug=${encodeURIComponent(c.nearest_slug)}&gap=${c.id}`
                            : `/kb/drafts/new?kind=create&gap=${c.id}`
                        }
                      >
                        {c.label === "update" ? "Sửa trang" : "Viết trang mới"}
                      </Link>
                      <button className="text-xs text-[var(--accent)] hover:underline" onClick={() => setDismissing(c.id)}>
                        Ẩn chủ đề…
                      </button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
            {report && report.clusters.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-[var(--text-muted)]">
                  {report.id ? "Không có chủ đề nào đủ lớn." : "Chưa có báo cáo; báo cáo chạy 06:00 thứ Hai."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <p className="mt-2 text-xs text-[var(--text-muted)]">
        update = chunk gần nhất có độ tương đồng ≥ kb_gaps.update_similarity (BR-F6-08). Chủ đề bị ẩn không xuất hiện trong
        kb_gaps.dismiss_days ngày.
      </p>
    </div>
  );
}
