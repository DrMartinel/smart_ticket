"use client";

// The authority queue (F6 · Authority queue 13-1049): pages a manager must grant, re-grant or
// re-tier. A grant pins the text the manager read (BR-F6-05); high-risk pages go one at a time.

import { Fragment, useCallback, useEffect, useState } from "react";
import { AUTHORITY_REASON_VI, DiffLines, KbTabs } from "@/components/kb/KbTabs";
import { vnTime } from "@/components/security/badges";
import { api, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { riskTierClasses } from "@/lib/badges";
import type { AuthorityQueueItemOut, BulkAllowedOut } from "@/lib/types/generated";

export default function AuthorityQueuePage() {
  const user = useRequireAuth();
  const [items, setItems] = useState<AuthorityQueueItemOut[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [read, setRead] = useState(false);
  const [reason, setReason] = useState("");
  const [tier, setTier] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<AuthorityQueueItemOut[]>("/api/kb/authority-queue")
      .then((r) => {
        setItems(r);
        setSelected(new Set());
      })
      .catch(() => setError("Không tải được hàng chờ."));
  }, []);

  useEffect(() => {
    if (user?.role === "manager") load();
  }, [user, load]);

  if (!user) return null;

  const run = async (call: () => Promise<unknown>, done: string) => {
    setError(null);
    setNotice(null);
    if (!read || !reason.trim()) {
      setError("Xác nhận đã đọc nội dung và ghi lý do.");
      return;
    }
    try {
      await call();
      setNotice(done);
      setReason("");
      setRead(false);
      setOpen(null);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code ?? err.status}: ${err.message}` : "Thao tác thất bại.");
    }
  };

  const grant = (slug: string, allowed: boolean) =>
    run(() => api.post(`/api/kb/${slug}/auto-reply-allowed`, { allowed, reason: reason.trim() }), allowed ? "Đã cấp quyền." : "Đã giữ không cấp quyền.");
  const retier = (slug: string) =>
    run(() => api.post(`/api/kb/${slug}/risk-tier`, { risk_tier: tier, reason: reason.trim() }), "Đã đổi mức rủi ro.");
  const bulk = () =>
    run(async () => {
      const r = await api.post<BulkAllowedOut>("/api/kb/auto-reply-allowed/bulk", {
        slugs: [...selected],
        allowed: true,
        reason: reason.trim(),
      });
      return r;
    }, `Đã cấp quyền ${selected.size} trang.`);

  const toggle = (slug: string) => {
    const next = new Set(selected);
    if (next.has(slug)) next.delete(slug);
    else next.add(slug);
    setSelected(next);
  };

  const confirmBox = (
    <>
      <label className="flex items-center gap-2 text-sm">
        <input type="checkbox" checked={read} onChange={(e) => setRead(e.target.checked)} />
        Tôi đã đọc nội dung này · I have read this text
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs text-[var(--text-muted)]">Lý do (mỗi trang một dòng nhật ký) · Reason</span>
        <input className="field" value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
    </>
  );

  return (
    <div className="mx-auto max-w-[1180px]">
      <KbTabs user={user} />
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Hàng chờ quyền · Authority queue</h1>
          <p className="text-xs text-[var(--text-muted)]">
            Trang chờ quyền trả lời tự động. Khi cấp, SHA-256 của nội dung bạn đã đọc được ghi lại (BR-F6-05).
          </p>
        </div>
      </header>

      {error && <p className="tone-danger mb-3 rounded-[5px] px-3 py-2 text-sm">{error}</p>}
      {notice && <p className="tone-ok mb-3 rounded-[5px] px-3 py-2 text-sm">{notice}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            <tr>
              <th className="w-10 px-4 py-2.5" />
              <th className="px-4 py-2.5 font-medium">Page</th>
              <th className="px-4 py-2.5 font-medium">Risk</th>
              <th className="px-4 py-2.5 font-medium">Why here</th>
              <th className="px-4 py-2.5 font-medium">Since</th>
              <th className="px-4 py-2.5" />
            </tr>
          </thead>
          <tbody>
            {items?.map((i) => {
              const high = i.article.risk_tier === "high";
              const slug = i.article.slug;
              return (
                <Fragment key={slug}>
                  <tr className={`border-t border-[var(--border)] ${high ? "bg-[var(--danger-soft)]" : ""}`}>
                    <td className="px-4 py-2.5">
                      <input
                        type="checkbox"
                        aria-label={`Select ${slug}`}
                        disabled={high}
                        checked={selected.has(slug)}
                        onChange={() => toggle(slug)}
                      />
                    </td>
                    <td className="px-4 py-2.5">
                      <div className="font-mono">{slug}</div>
                      <div className="text-xs text-[var(--text-muted)]">{i.article.title}</div>
                    </td>
                    <td className="px-4 py-2.5">
                      <span className={`badge ${riskTierClasses(i.article.risk_tier)}`}>{i.article.risk_tier}</span>
                      {i.proposed_risk_tier && i.proposed_risk_tier !== i.article.risk_tier && (
                        <span className="ml-1 text-xs text-[var(--text-muted)]">→ {i.proposed_risk_tier}</span>
                      )}
                    </td>
                    <td className="px-4 py-2.5">{AUTHORITY_REASON_VI[i.reason] ?? i.reason}</td>
                    <td className="px-4 py-2.5">{i.published_at ? vnTime(i.published_at) : "—"}</td>
                    <td className="px-4 py-2.5 text-right">
                      <button
                        className={`text-sm ${high ? "text-[var(--danger)]" : "text-[var(--accent)]"} hover:underline`}
                        onClick={() => {
                          setOpen(open === slug ? null : slug);
                          setTier(i.proposed_risk_tier ?? i.article.risk_tier);
                        }}
                      >
                        {high ? "Duyệt riêng" : "Xem nội dung"}
                      </button>
                    </td>
                  </tr>
                  {open === slug && (
                    <tr className="bg-[var(--surface-2)]">
                      <td colSpan={6} className="px-4 py-4">
                        <div className="flex flex-col gap-3">
                          {i.change_note && <p className="text-sm">Ghi chú: {i.change_note}</p>}
                          {i.published_by && <p className="text-xs text-[var(--text-muted)]">Xuất bản bởi {i.published_by}</p>}
                          <div className="text-xs text-[var(--text-muted)]">Thay đổi so với nội dung trước</div>
                          <DiffLines lines={[...i.title_diff, ...i.body_diff]} />
                          {confirmBox}
                          <div className="flex flex-wrap items-end justify-end gap-2">
                            <select className="field w-32" aria-label="Risk tier" value={tier} onChange={(e) => setTier(e.target.value)}>
                              {["low", "medium", "high"].map((t) => (
                                <option key={t}>{t}</option>
                              ))}
                            </select>
                            <button className="btn btn-secondary" disabled={tier === i.article.risk_tier} onClick={() => void retier(slug)}>
                              Đổi mức rủi ro
                            </button>
                            <button className="btn btn-secondary" onClick={() => void grant(slug, false)}>
                              Không cấp
                            </button>
                            <button className="btn btn-primary" disabled={i.article.risk_tier !== tier} onClick={() => void grant(slug, true)}>
                              Cấp quyền trả lời tự động
                            </button>
                          </div>
                        </div>
                      </td>
                    </tr>
                  )}
                </Fragment>
              );
            })}
            {items?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-[var(--text-muted)]">
                  Không có trang nào chờ quyết định.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {selected.size > 0 && open === null && (
        <section className="card mt-4 flex flex-col gap-3 p-5">
          <h2 className="text-sm font-medium">Duyệt {selected.size} trang</h2>
          {confirmBox}
          <p className="text-xs text-[var(--danger)]">
            Trang rủi ro cao luôn được duyệt riêng; một yêu cầu hàng loạt có trang rủi ro cao bị từ chối và không trang nào
            được duyệt (BR-F6-06, ADR-0027).
          </p>
          <div className="flex justify-end">
            <button className="btn btn-primary" onClick={() => void bulk()}>
              Duyệt các trang đã chọn ({selected.size})
            </button>
          </div>
        </section>
      )}
    </div>
  );
}
