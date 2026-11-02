"use client";

// The runbook catalog (F12 UC-F12-03 · 20-2142): a workflow admin drafts, another manager approves.

import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";
import type { RunbookOut } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Checkbox } from "@/components/ui/checkbox";

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
    <div className="mt-2 rounded-md bg-muted p-3 text-xs">
      <p className="mb-1 font-medium">
        Thay đổi chờ duyệt · {runbook.drafted_by} · {runbook.drafted_at && dateTime(runbook.drafted_at)}
      </p>
      {changed.length === 0 && <p className="text-muted-foreground">Không có trường nào khác bản đang chạy.</p>}
      {changed.map((f) => (
        <p key={f} className="font-mono">
          {f}: <span className="text-danger line-through">{JSON.stringify(live[f])}</span> →{" "}
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
          <p className="mt-1 max-w-[760px] text-xs text-muted-foreground">
            Runbook luôn cần người duyệt trên từng phiếu (ADR-0006). Mọi thay đổi ở đây chỉ có hiệu lực khi một quản lý khác người soạn
            duyệt; trước đó bản cũ vẫn chạy.
          </p>
        </div>
        {admin && (
          <Button
            onClick={() => {
              setIsNew(true);
              setForm(EMPTY);
            }}
          >
            Thêm runbook
          </Button>
        )}
      </header>

      {error && <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}

      {form && (
        <Card asChild>
          <form
            className="mb-5 grid grid-cols-1 gap-3 p-4 text-sm md:grid-cols-2"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <p className="font-medium md:col-span-2">{isNew ? "Runbook mới" : `Soạn thay đổi cho ${form.code}`}</p>
            {isNew && (
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Mã (RB-…)</span>
                <Input className="font-mono" value={form.code} onChange={(e) => setForm({ ...form, code: e.target.value })} required />
              </label>
            )}
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Tên</span>
              <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} required />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Executor</span>
              <NativeSelect value={form.executor} onChange={(e) => setForm({ ...form, executor: e.target.value })}>
                <option value="keycloak">keycloak</option>
                <option value="n8n">n8n</option>
                <option value="mock">mock (chỉ để thử)</option>
              </NativeSelect>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Trường bắt buộc (phân cách bằng dấu phẩy)</span>
              <Input
                className="font-mono"
                value={form.required_fields}
                onChange={(e) => setForm({ ...form, required_fields: e.target.value })}
              />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Đối tượng</span>
              <NativeSelect value={form.target_rule} onChange={(e) => setForm({ ...form, target_rule: e.target.value })}>
                <option value="reporter">Chỉ người gửi yêu cầu</option>
                <option value="any">Bất kỳ ai</option>
              </NativeSelect>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Rủi ro</span>
              <NativeSelect value={form.risk} onChange={(e) => setForm({ ...form, risk: e.target.value })}>
                <option value="low">Thấp</option>
                <option value="high">Cao (cần quản lý duyệt lần hai)</option>
              </NativeSelect>
            </label>
            <label className="flex items-center gap-2">
              <Checkbox checked={form.is_active} onCheckedChange={(checked) => setForm({ ...form, is_active: checked === true })} />
              <span>Đang dùng</span>
            </label>
            <label className="flex flex-col gap-1 md:col-span-2">
              <span className="text-xs text-muted-foreground">Config (JSON: URL n8n, hoặc action Keycloak và nhóm được cấp)</span>
              <Textarea className="min-h-[120px] font-mono text-xs" value={form.config} onChange={(e) => setForm({ ...form, config: e.target.value })} />
            </label>
            <div className="flex gap-2 md:col-span-2">
              <Button type="submit" disabled={busy}>
                {isNew ? "Tạo (chờ duyệt)" : "Gửi thay đổi (chờ duyệt)"}
              </Button>
              <Button variant="outline" type="button" onClick={() => setForm(null)}>
                Huỷ
              </Button>
            </div>
          </form>
        </Card>
      )}

      {rows === null && !error && <p className="text-sm text-muted-foreground">Loading…</p>}
      {rows && (
        <Card asChild>
          <section className="overflow-x-auto">
            <Table className="w-full min-w-[860px] text-sm">
              <TableHeader className="bg-muted text-left text-xs text-muted-foreground">
                <TableRow>
                  <TableHead className="px-4 py-2.5 font-medium">Runbook</TableHead>
                  <TableHead className="px-4 py-2.5 font-medium">Executor · Config</TableHead>
                  <TableHead className="px-4 py-2.5 font-medium">Quy tắc</TableHead>
                  <TableHead className="px-4 py-2.5 font-medium">Trạng thái</TableHead>
                  <TableHead className="w-40 px-4 py-2.5" />
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((r) => (
                  <TableRow key={r.code} className="border-t border-border align-top">
                    <TableCell className="px-4 py-3">
                      <span className="block font-mono text-xs">{r.code}</span>
                      <span className="font-medium">{r.title}</span>
                      <Changes runbook={r} />
                    </TableCell>
                    <TableCell className="px-4 py-3">
                      <Badge variant="neutral">{r.executor}</Badge>
                      <pre className="mt-1 whitespace-pre-wrap break-all font-mono text-xs text-muted-foreground">
                        {JSON.stringify(r.config)}
                      </pre>
                    </TableCell>
                    <TableCell className="px-4 py-3 text-xs">
                      <p>{r.target_rule === "reporter" ? "Chỉ người gửi" : "Bất kỳ ai"}</p>
                      <p>{r.risk === "high" ? "Rủi ro cao · 2 người duyệt" : "Rủi ro thấp"}</p>
                      <p className="font-mono text-muted-foreground">{r.required_fields.join(", ")}</p>
                    </TableCell>
                    <TableCell className="px-4 py-3 text-xs">
                      <div className="flex flex-wrap gap-1">
                        {r.runnable ? <Badge variant="ok">Đã duyệt</Badge> : <Badge variant="warn">Chưa duyệt</Badge>}
                        {!r.is_active && <Badge variant="neutral">Tắt</Badge>}
                        {r.pending_change && <Badge variant="info">Có thay đổi chờ duyệt</Badge>}
                      </div>
                      {r.approved_by && (
                        <p className="mt-1 text-muted-foreground">
                          {r.approved_by} · {r.approved_at && dateTime(r.approved_at)}
                        </p>
                      )}
                    </TableCell>
                    <TableCell className="px-4 py-3 text-right">
                      <span className="inline-flex flex-wrap justify-end gap-2 text-xs">
                        {admin && (
                          <Button variant="link" size="inline"
                            
                            onClick={() => {
                              setIsNew(false);
                              setForm(formOf(r));
                            }}
                          >
                            Sửa
                          </Button>
                        )}
                        {manager && (r.pending_change || !r.approved_at) && r.drafted_by !== user.username && (
                          <Button variant="link" size="inline"
                            
                            disabled={busy}
                            onClick={() => void act(() => api.post(`/api/itsm/runbooks/${r.code}/approve`))}
                          >
                            Duyệt
                          </Button>
                        )}
                      </span>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </section>
        </Card>
      )}
    </div>
  );
}
