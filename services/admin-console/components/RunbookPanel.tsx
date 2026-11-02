"use client";

// A runbook proposal on its review item (F12 UC-F12-01, 02): the payload the approver edits, the
// execution, a second manager's approval and the verdict on an unknown outcome.

import { useCallback, useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { dateTime } from "@/lib/format";
import type { RunbookExecutionOut, RunbookPanelOut } from "@/lib/types/generated";

const STATE_VI: Record<string, { label: string; tone: string }> = {
  awaiting_second_approval: { label: "Chờ quản lý duyệt lần hai", tone: "tone-warn" },
  queued: { label: "Đang chờ chạy", tone: "tone-info" },
  running: { label: "Đang chạy", tone: "tone-info" },
  succeeded: { label: "Thành công", tone: "tone-ok" },
  failed: { label: "Thất bại", tone: "tone-danger" },
  unknown: { label: "Chưa rõ kết quả", tone: "tone-warn" },
};

const REFUSAL_VI: Record<string, string> = {
  target_not_reporter: "Runbook này chỉ được áp dụng cho chính người gửi yêu cầu.",
  missing_fields: "Thiếu trường bắt buộc.",
  group_not_allowed: "Nhóm này không nằm trong danh sách được cấp.",
  runbook_not_approved: "Runbook chưa được quản lý duyệt trong danh mục.",
  not_approved: "Đề xuất chưa được duyệt.",
  execution_exists: "Đề xuất này đã có một lần chạy chưa thất bại.",
  self_approval: "Lần duyệt thứ hai phải do một quản lý khác.",
};

function message(err: unknown): string {
  if (!(err instanceof ApiError)) return "Không thực hiện được.";
  return (err.code && REFUSAL_VI[err.code]) || `${err.code ?? err.status}: ${err.message}`;
}

function Execution({
  execution,
  role,
  username,
  busy,
  onSecond,
  onResolve,
}: {
  execution: RunbookExecutionOut;
  role: string;
  username: string;
  busy: boolean;
  onSecond: () => void;
  onResolve: (state: "succeeded" | "failed", note: string) => void;
}) {
  const [note, setNote] = useState("");
  const state = STATE_VI[execution.state] ?? { label: execution.state, tone: "" };
  const mine = [execution.approved_by, execution.executed_by].includes(username);
  return (
    <li className="rounded-[5px] border border-[var(--border)] p-3 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className={`badge ${state.tone}`}>{state.label}</span>
        <span className="text-xs text-[var(--text-muted)]">
          Lần {execution.attempt} · {dateTime(execution.executed_at)}
        </span>
      </div>
      <dl className="mt-2 grid grid-cols-[140px_1fr] gap-x-3 gap-y-1 text-xs">
        <dt className="text-[var(--text-muted)]">Dữ liệu đã chạy</dt>
        <dd className="font-mono">{JSON.stringify(execution.executed_payload)}</dd>
        <dt className="text-[var(--text-muted)]">Người duyệt</dt>
        <dd>
          {execution.approved_by ?? "—"} · chạy bởi {execution.executed_by}
          {execution.second_approver && ` · duyệt lần hai: ${execution.second_approver}`}
        </dd>
        {execution.external_ref && (
          <>
            <dt className="text-[var(--text-muted)]">Tham chiếu</dt>
            <dd className="font-mono">{execution.external_ref}</dd>
          </>
        )}
        {execution.error && (
          <>
            <dt className="text-[var(--text-muted)]">Lỗi</dt>
            <dd className="text-[var(--danger)]">{execution.error}</dd>
          </>
        )}
        {execution.resolved_by && (
          <>
            <dt className="text-[var(--text-muted)]">Xác nhận</dt>
            <dd>
              {execution.resolved_by}: “{execution.resolution_note}”
            </dd>
          </>
        )}
      </dl>
      {execution.state === "awaiting_second_approval" && role === "manager" && !mine && (
        <button className="btn btn-primary mt-3" disabled={busy} onClick={onSecond}>
          Duyệt lần hai và chạy
        </button>
      )}
      {execution.state === "unknown" && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input
            className="field min-w-[240px] flex-1"
            placeholder="Đã kiểm tra hệ thống đích: ghi chú (bắt buộc)"
            value={note}
            onChange={(e) => setNote(e.target.value)}
          />
          <button className="btn btn-secondary" disabled={busy || !note.trim()} onClick={() => onResolve("succeeded", note)}>
            Đã thành công
          </button>
          <button className="btn btn-secondary" disabled={busy || !note.trim()} onClick={() => onResolve("failed", note)}>
            Đã thất bại
          </button>
        </div>
      )}
    </li>
  );
}

export default function RunbookPanel({
  itemId,
  role,
  username,
  onChanged,
}: {
  itemId: string;
  role: string;
  username: string;
  onChanged: () => void;
}) {
  const [panel, setPanel] = useState<RunbookPanelOut | null>(null);
  const [payload, setPayload] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .get<RunbookPanelOut>(`/api/itsm/review-items/${itemId}/runbook`)
      .then((p) => {
        setPanel(p);
        const fields = new Set([...(p.runbook?.required_fields ?? []), ...Object.keys(p.draft_payload)]);
        setPayload(Object.fromEntries([...fields].map((f) => [f, String(p.draft_payload[f] ?? "")])));
      })
      .catch((err) => setError(message(err)));
  }, [itemId]);

  useEffect(load, [load]);

  const run = async (call: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await call();
    } catch (err) {
      setError(message(err));
    } finally {
      setBusy(false);
      load();
      onChanged();
    }
  };

  if (!panel) return error ? <p className="text-sm text-[var(--danger)]">{error}</p> : null;
  const runbook = panel.runbook;
  const open = panel.executions.some((e) => e.state !== "failed");

  return (
    <div className="mt-4 flex flex-col gap-3 border-t border-[var(--border)] pt-4">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span className="font-medium">Runbook · {panel.runbook_id ?? "—"}</span>
        {runbook && (
          <>
            <span className="text-[var(--text-muted)]">{runbook.title}</span>
            <span className={`badge ${runbook.risk === "high" ? "tone-danger" : "tone-info"}`}>
              {runbook.risk === "high" ? "Rủi ro cao · cần 2 người duyệt" : "Rủi ro thấp"}
            </span>
            {runbook.target_rule === "reporter" && <span className="badge">Chỉ cho người gửi</span>}
            <span className="badge">{runbook.executor}</span>
          </>
        )}
      </div>
      {runbook && !runbook.runnable && (
        <p className="tone-warn rounded-[5px] px-3 py-2 text-xs">Runbook chưa được quản lý duyệt trong danh mục, chưa thể chạy.</p>
      )}
      {!open && (
        <form
          className="flex flex-col gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void run(async () => {
              try {
                await api.post(`/api/itsm/review-items/${itemId}/execute`, { payload });
              } catch (err) {
                if (err instanceof ApiError && err.code === "second_approval_required") return;
                throw err;
              }
            });
          }}
        >
          <p className="text-xs text-[var(--text-muted)]">
            Dữ liệu do AI đề xuất. Kiểm tra và sửa trước khi chạy: thứ được chạy là thứ bạn thấy ở đây.
          </p>
          {Object.keys(payload).map((field) => (
            <label key={field} className="grid grid-cols-[160px_1fr] items-center gap-2 text-sm">
              <span className="font-mono text-xs">{field}</span>
              <input
                className="field font-mono"
                value={payload[field]}
                onChange={(e) => setPayload({ ...payload, [field]: e.target.value })}
              />
            </label>
          ))}
          <div>
            <button type="submit" className="btn btn-primary" disabled={busy || !panel.approved || !runbook?.runnable}>
              Chạy runbook
            </button>
            {!panel.approved && <span className="ml-3 text-xs text-[var(--text-muted)]">Duyệt đề xuất trước (ADR-0006).</span>}
          </div>
        </form>
      )}
      {error && <p className="tone-danger rounded-[5px] px-3 py-2 text-sm">{error}</p>}
      {panel.executions.length > 0 && (
        <ul className="flex flex-col gap-2">
          {panel.executions.map((e) => (
            <Execution
              key={e.id}
              execution={e}
              role={role}
              username={username}
              busy={busy}
              onSecond={() => void run(() => api.post(`/api/itsm/executions/${e.id}/second-approval`))}
              onResolve={(state, note) => void run(() => api.post(`/api/itsm/executions/${e.id}/resolve`, { state, note }))}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
