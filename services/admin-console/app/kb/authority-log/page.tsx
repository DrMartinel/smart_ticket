"use client";

// The authority log (F6 · Authority log 13-1180): every change to a page's auto-reply authority
// or risk tier, filterable, with an audited CSV export.

import { useCallback, useEffect, useState } from "react";
import { KbTabs } from "@/components/kb/KbTabs";
import { vnTime } from "@/components/security/badges";
import { api, download } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { AuthorityLogOut } from "@/lib/types/generated";

interface Filters {
  slug: string;
  actor: string;
  field: string;
  from: string;
  to: string;
}

const EMPTY: Filters = { slug: "", actor: "", field: "", from: "", to: "" };

function query(f: Filters): string {
  const params = new URLSearchParams();
  for (const [k, v] of Object.entries(f)) if (v.trim()) params.set(k, v.trim());
  return params.toString();
}

export default function AuthorityLogPage() {
  const user = useRequireAuth();
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
  const [rows, setRows] = useState<AuthorityLogOut[] | null>(null);
  const [count, setCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    const q = query(applied);
    api
      .get<{ items: AuthorityLogOut[]; count: number }>(`/api/kb/authority-log?limit=200${q ? `&${q}` : ""}`)
      .then((page) => {
        setRows(page.items);
        setCount(page.count);
        setError(null);
      })
      .catch(() => setError("Không tải được nhật ký."));
  }, [applied]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  if (!user) return null;

  const exportCsv = async () => {
    try {
      const q = query(applied);
      const blob = await download(`/api/kb/authority-log.csv${q ? `?${q}` : ""}`);
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "kb-authority-log.csv";
      link.click();
      URL.revokeObjectURL(link.href);
    } catch {
      setError("Không xuất được CSV.");
    }
  };

  const input = (key: keyof Filters, label: string, width: string, type = "text") => (
    <label className={`flex flex-col gap-1 ${width}`}>
      <span className="text-[11px] text-[var(--text-muted)]">{label}</span>
      <input className="field" type={type} value={filters[key]} onChange={(e) => setFilters({ ...filters, [key]: e.target.value })} />
    </label>
  );

  return (
    <div className="mx-auto max-w-[1180px]">
      <KbTabs user={user} />
      <header className="mb-4">
        <h1 className="text-xl font-semibold">Nhật ký quyền · Authority log</h1>
        <p className="text-xs text-[var(--text-muted)]">Mọi thay đổi quyền trả lời tự động và mức rủi ro. Việc xuất CSV được ghi audit.</p>
      </header>

      <form
        className="mb-4 flex flex-wrap items-end gap-3 text-sm"
        onSubmit={(e) => {
          e.preventDefault();
          setApplied(filters);
        }}
      >
        {input("slug", "Page", "w-64")}
        {input("actor", "Actor", "w-40")}
        <label className="flex w-44 flex-col gap-1">
          <span className="text-[11px] text-[var(--text-muted)]">Field</span>
          <select className="field" value={filters.field} onChange={(e) => setFilters({ ...filters, field: e.target.value })}>
            <option value="">all</option>
            <option value="auto_reply_allowed">auto_reply_allowed</option>
            <option value="risk_tier">risk_tier</option>
          </select>
        </label>
        {input("from", "From", "w-40", "date")}
        {input("to", "To", "w-40", "date")}
        <button type="submit" className="btn btn-secondary">
          Lọc
        </button>
        <button type="button" className="btn btn-secondary ml-auto" onClick={() => void exportCsv()}>
          Xuất CSV
        </button>
      </form>

      {error && <p className="tone-danger mb-3 rounded-[5px] px-3 py-2 text-sm">{error}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[900px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2.5 font-medium">When</th>
              <th className="px-4 py-2.5 font-medium">Page</th>
              <th className="px-4 py-2.5 font-medium">Field</th>
              <th className="px-4 py-2.5 font-medium">Change</th>
              <th className="px-4 py-2.5 font-medium">Actor</th>
              <th className="px-4 py-2.5 font-medium">Reason</th>
            </tr>
          </thead>
          <tbody>
            {rows?.map((r) => (
              <tr key={r.id} className="border-t border-[var(--border)] align-top">
                <td className="whitespace-nowrap px-4 py-2.5">{vnTime(r.changed_at)}</td>
                <td className="px-4 py-2.5 font-mono text-xs">{r.slug}</td>
                <td className="px-4 py-2.5">{r.field}</td>
                <td className="whitespace-nowrap px-4 py-2.5">
                  {r.old_value ?? "—"} → {r.new_value ?? "—"}
                </td>
                <td className="px-4 py-2.5">{r.actor}</td>
                <td className="px-4 py-2.5">{r.reason}</td>
              </tr>
            ))}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-[var(--text-muted)]">
                  Không có dòng nào.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      {rows && count > rows.length && <p className="mt-2 text-xs text-[var(--text-muted)]">Hiển thị {rows.length} / {count}; lọc hẹp hơn hoặc xuất CSV.</p>}
    </div>
  );
}
