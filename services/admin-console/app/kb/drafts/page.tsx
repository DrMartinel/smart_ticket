"use client";

// KB drafts (F6 · KB drafts 13-828): what is being written, what waits for review.

import Link from "next/link";
import { useEffect, useState } from "react";
import { DraftStateChip, KbTabs, KIND_VI, canEditKb } from "@/components/kb/KbTabs";
import { vnTime } from "@/components/security/badges";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { DraftOut } from "@/lib/types/generated";

const STATES = ["", "draft", "in_review", "changes_requested", "conflict", "published", "withdrawn"];

export default function DraftsPage() {
  const user = useRequireAuth();
  const [state, setState] = useState("in_review");
  const [mine, setMine] = useState(false);
  const [rows, setRows] = useState<DraftOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user || !canEditKb(user)) return;
    const params = new URLSearchParams({ limit: "100" });
    if (state) params.set("state", state);
    if (mine) params.set("author", user.username);
    api
      .get<{ items: DraftOut[] }>(`/api/kb/drafts?${params}`)
      .then((page) => {
        setRows(page.items);
        setError(null);
      })
      .catch(() => setError("Không tải được bản nháp."));
  }, [user, state, mine]);

  if (!user) return null;

  return (
    <div className="mx-auto max-w-[1180px]">
      <KbTabs user={user} />
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Bản nháp · Drafts</h1>
          <p className="text-xs text-[var(--text-muted)]">
            Bản nháp không bao giờ được truy xuất; một người khác duyệt trước khi xuất bản (BR-F6-01, 02).
          </p>
        </div>
        <div className="flex items-end gap-3 text-sm">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={mine} onChange={(e) => setMine(e.target.checked)} />
            Của tôi
          </label>
          <select className="field" aria-label="State" value={state} onChange={(e) => setState(e.target.value)}>
            {STATES.map((s) => (
              <option key={s} value={s}>
                {s || "Tất cả"}
              </option>
            ))}
          </select>
          <Link href="/kb/drafts/new" className="btn btn-primary">
            Trang mới
          </Link>
        </div>
      </header>

      {error && <p className="tone-danger mb-3 rounded-[5px] px-3 py-2 text-sm">{error}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[820px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2.5 font-medium">Page</th>
              <th className="px-4 py-2.5 font-medium">Kind</th>
              <th className="px-4 py-2.5 font-medium">State</th>
              <th className="px-4 py-2.5 font-medium">Author</th>
              <th className="px-4 py-2.5 font-medium">Reviewer</th>
              <th className="px-4 py-2.5 font-medium">Updated</th>
            </tr>
          </thead>
          <tbody>
            {rows?.map((d) => (
              <tr key={d.id} className="border-t border-[var(--border)]">
                <td className="px-4 py-2.5">
                  <Link href={`/kb/drafts/${d.id}`} className="font-medium text-[var(--accent)] hover:underline">
                    {d.title}
                  </Link>
                  <div className="font-mono text-xs text-[var(--text-muted)]">{d.slug}</div>
                </td>
                <td className="px-4 py-2.5">{KIND_VI[d.kind] ?? d.kind}</td>
                <td className="px-4 py-2.5">
                  <DraftStateChip state={d.state} />
                </td>
                <td className="px-4 py-2.5">{d.author.username}</td>
                <td className="px-4 py-2.5">{d.reviewer?.username ?? "—"}</td>
                <td className="px-4 py-2.5">{vnTime(d.updated_at)}</td>
              </tr>
            ))}
            {rows?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-[var(--text-muted)]">
                  Không có bản nháp.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
