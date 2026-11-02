"use client";

// The runbook catalog (F12 UC-F12-03 · 20-2142): a workflow admin drafts, another manager approves.

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";
import type { RunbookOut } from "@/lib/types/generated";

type Form = {
  code: string;
  title: string;
  executor: string;
  config: string;
  required_fields: string;
  target_rule: string;
  risk: string;
  is_active: boolean;
};

const EMPTY: Form = {
  code: "",
  title: "",
  executor: "keycloak",
  config: '{\n  "action": "send_password_reset"\n}',
  required_fields: "target_username",
  target_rule: "reporter",
  risk: "low",
  is_active: true,
};

const FIELDS: (keyof Form)[] = ["title", "executor", "config", "required_fields", "target_rule", "risk", "is_active"];

function formOf(r: RunbookOut): Form {
  const live = { ...r, ...(r.pending_change ?? {}) } as RunbookOut;
  return {
    code: r.code,
    title: live.title,
    executor: live.executor,
    config: JSON.stringify(live.config, null, 2),
    required_fields: live.required_fields.join(", "),
    target_rule: live.target_rule,
    risk: live.risk,
    is_active: live.is_active,
  };
}

function bodyOf(form: Form): Record<string, unknown> {
  return {
    title: form.title,
    executor: form.executor,
    config: JSON.parse(form.config),
    required_fields: form.required_fields.split(",").map((f) => f.trim()).filter(Boolean),
    target_rule: form.target_rule,
    risk: form.risk,
    is_active: form.is_active,
  };
}

function refusal(err: unknown): string {
  if (err instanceof SyntaxError) return "Config không phải JSON hợp lệ.";
  if (!(err instanceof ApiError)) return "Không lưu được.";
  if (err.code === "self_approval") return "Người soạn thay đổi không tự duyệt được: cần một quản lý khác.";
  if (err.code === "group_not_allowed") return `Nhóm không được phép cấp: ${err.message}`;
  return `${err.code ?? err.status}: ${err.message}`;
}

function Changes({ runbook }: { runbook: RunbookOut }) {
  if (!runbook.pending_change) return null;
  const pending = runbook.pending_change as Record<string, unknown>;
  const live = runbook as unknown as Record<string, unknown>;
  const changed = FIELDS.filter((f) => JSON.stringify(pending[f]) !== JSON.stringify(live[f]));
  return (
    <div className="mt-2 rounded-[5px] bg-[var(--surface-2)] p-3 text-xs">
      <p className="mb-1 font-medium">
        Thay đổi chờ duyệt · {runbook.drafted_by} · {runbook.drafted_at && dateTime(runbook.drafted_at)}
      </p>
      {changed.length === 0 && <p className="text-[var(--text-muted)]">Không có trường nào khác bản đang chạy.</p>}
      {changed.map((f) => (
        <p key={f} className="font-mono">
          {f}: <span className="text-[var(--danger)] line-through">{JSON.stringify(live[f])}</span> →{" "}
          <span className="text-[var(--ok,inherit)]">{JSON.stringify(pending[f])}</span>
        </p>
      ))}
    </div>
  );
}

export default function RunbooksPage() {
  const user = useRequireAuth();
  const [rows, setRows] = useState<RunbookOut[] | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [isNew, setIsNew] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .get<RunbookOut[]>("/api/itsm/runbooks")
      .then(setRows)
      .catch((err) => setError(refusal(err)));
  }, []);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  if (!user) return null;
  const admin = (user.capabilities ?? []).includes("workflow_admin");
  const manager = user.role === "manager";

  const act = async (call: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await call();
      setForm(null);
      load();
    } catch (err) {
      setError(refusal(err));
    } finally {
      setBusy(false);
    }
  };

  const save = () =>
    act(async () => {
      if (!form) return;
      const body = bodyOf(form);
      if (isNew) await api.post("/api/itsm/runbooks", { code: form.code.trim(), ...body });
      else await api.patch(`/api/itsm/runbooks/${form.code}`, body);
    });

  return (
    <div className="mx-auto max-w-[1280px]">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Danh mục runbook · Runbook catalog</h1>
          <p className="mt-1 max-w-[760px] text-xs text-[var(--text-muted)]">
            Runbook luôn cần người duyệt trên từng phiếu (ADR-0006). Mọi thay đổi ở đây chỉ có hiệu lực khi một quản lý khác người soạn
            duyệt; trước đó bản cũ vẫn chạy.
          </p>
        </div>
        {admin && (
          <button
            className="btn btn-primary"
            onClick={() => {
              setIsNew(true);
              setForm(EMPTY);
            }}
          >
            Thêm runbook
          </button>
        )}
      </header>

      {error && <p className="tone-danger mb-3 rounded-[5px] px-3 py-2 text-sm">{error}</p>}

      {form && (
        <form
          className="card mb-5 grid grid-cols-1 gap-3 p-4 text-sm md:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <p className="font-medium md:col-span-2">{isNew ? "Runbook mới" : `Soạn thay đổi cho ${form.code}`}</p>
          {isNew && (
            <label className="flex flex-col gap-1">
              <span className="text-xs text-[var(--text-muted)]">Mã (RB-…)</span>
              <input className="field font-mono" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
            </label>
          )}
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Tên</span>
            <input className="field" value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Executor</span>
            <select className="field" value={form.executor} onChange={(e) => setForm({ ...form, executor: e.target.value })}>
              <option value="keycloak">keycloak</option>
              <option value="n8n">n8n</option>
              <option value="mock">mock (chỉ để thử)</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Trường bắt buộc (phân cách bằng dấu phẩy)</span>
            <input
              className="field font-mono"
              value={form.required_fields}
              onChange={(e) => setForm({ ...form, required_fields: e.target.value })}
            />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Đối tượng</span>
            <select className="field" value={form.target_rule} onChange={(e) => setForm({ ...form, target_rule: e.target.value })}>
              <option value="reporter">Chỉ người gửi yêu cầu</option>
              <option value="any">Bất kỳ ai</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-[var(--text-muted)]">Rủi ro</span>
            <select className="field" value={form.risk} onChange={(e) => setForm({ ...form, risk: e.target.value })}>
              <option value="low">Thấp</option>
              <option value="high">Cao (cần quản lý duyệt lần hai)</option>
            </select>
          </label>
          <label className="flex items-center gap-2">
            <input type="checkbox" checked={form.is_active} onChange={(e) => setForm({ ...form, is_active: e.target.checked })} />
            <span>Đang dùng</span>
          </label>
          <label className="flex flex-col gap-1 md:col-span-2">
            <span className="text-xs text-[var(--text-muted)]">Config (JSON: URL n8n, hoặc action Keycloak và nhóm được cấp)</span>
            <textarea className="field min-h-[120px] font-mono text-xs" value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })} />
          </label>
          <div className="flex gap-2 md:col-span-2">
            <button type="submit" className="btn btn-primary" disabled={busy}>
              {isNew ? "Tạo (chờ duyệt)" : "Gửi thay đổi (chờ duyệt)"}
            </button>
            <button type="button" className="btn btn-secondary" onClick={() => setForm(null)}>
              Huỷ
            </button>
          </div>
        </form>
      )}

      {rows === null && !error && <p className="text-sm text-[var(--text-muted)]">Loading…</p>}
      {rows && (
        <section className="card overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead className="bg-[var(--surface-2)] text-left text-xs text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-2.5 font-medium">Runbook</th>
                <th className="px-4 py-2.5 font-medium">Executor · Config</th>
                <th className="px-4 py-2.5 font-medium">Quy tắc</th>
                <th className="px-4 py-2.5 font-medium">Trạng thái</th>
                <th className="w-40 px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.code} className="border-t border-[var(--border)] align-top">
                  <td className="px-4 py-3">
                    <span className="block font-mono text-xs">{r.code}</span>
                    <span className="font-medium">{r.title}</span>
                    <Changes runbook={r} />
                  </td>
                  <td className="px-4 py-3">
                    <span className="badge">{r.executor}</span>
                    <pre className="mt-1 whitespace-pre-wrap break-all font-mono text-xs text-[var(--text-muted)]">
                      {JSON.stringify(r.config)}
                    </pre>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    <p>{r.target_rule === "reporter" ? "Chỉ người gửi" : "Bất kỳ ai"}</p>
                    <p>{r.risk === "high" ? "Rủi ro cao · 2 người duyệt" : "Rủi ro thấp"}</p>
                    <p className="font-mono text-[var(--text-muted)]">{r.required_fields.join(", ")}</p>
                  </td>
                  <td className="px-4 py-3 text-xs">
                    <div className="flex flex-wrap gap-1">
                      {r.runnable ? <span className="badge tone-ok">Đã duyệt</span> : <span className="badge tone-warn">Chưa duyệt</span>}
                      {!r.is_active && <span className="badge">Tắt</span>}
                      {r.pending_change && <span className="badge tone-info">Có thay đổi chờ duyệt</span>}
                    </div>
                    {r.approved_by && (
                      <p className="mt-1 text-[var(--text-muted)]">
                        {r.approved_by} · {r.approved_at && dateTime(r.approved_at)}
                      </p>
                    )}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <span className="inline-flex flex-wrap justify-end gap-2 text-xs">
                      {admin && (
                        <button
                          className="text-[var(--accent)] hover:underline"
                          onClick={() => {
                            setIsNew(false);
                            setForm(formOf(r));
                          }}
                        >
                          Sửa
                        </button>
                      )}
                      {manager && (r.pending_change || !r.approved_at) && r.drafted_by !== user.username && (
                        <button
                          className="text-[var(--accent)] hover:underline"
                          disabled={busy}
                          onClick={() => void act(() => api.post(`/api/itsm/runbooks/${r.code}/approve`))}
                        >
                          Duyệt
                        </button>
                      )}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
