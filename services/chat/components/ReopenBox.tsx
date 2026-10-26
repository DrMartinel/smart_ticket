"use client";

// "Chưa giải quyết được": reopen within 7 days, else a new ticket linked to this one (UC-F3-04).

import Link from "next/link";
import { useState } from "react";
import { ApiError, requesterApi } from "@/lib/api";
import type { ReopenOut } from "@/lib/types/generated";
import { day } from "./Rating";

export default function ReopenBox({
  publicId,
  until,
  onDone,
}: {
  publicId: string;
  until: string | null;
  onDone?: (result: ReopenOut) => void;
}) {
  const [reason, setReason] = useState("");
  const [result, setResult] = useState<ReopenOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const late = until !== null && Date.parse(until) < Date.now();

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      const done = await requesterApi.reopen(publicId, reason);
      setResult(done);
      onDone?.(done);
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "reason_required"
          ? "Hãy cho biết lý do · Say what still doesn't work."
          : "Không mở lại được · Couldn't reopen it.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return result.reopened ? (
      <p className="text-sm">Đã mở lại · Reopened. A person on the support team will take it from here.</p>
    ) : (
      <p className="text-sm">
        Đã tạo yêu cầu mới · A new ticket{" "}
        <Link href={`/tickets/${result.new_ticket}`} className="font-mono text-[var(--accent)] underline">
          {result.new_ticket}
        </Link>{" "}
        is linked to this one.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-[var(--text-muted)]">
        {until && !late
          ? `Mở lại trước ${day(until)}. After that we open a new ticket linked to this one.`
          : "Quá 7 ngày: we open a new ticket linked to this one."}
      </p>
      <textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        maxLength={2000}
        placeholder="Còn lỗi gì? · What still doesn't work?"
        aria-label="Why it isn't solved"
        className="field min-h-[64px] text-sm"
      />
      <button onClick={() => void send()} disabled={busy || !reason.trim()} className="btn btn-secondary self-start">
        {late ? "Tạo yêu cầu mới · New linked ticket" : "Mở lại · Reopen"}
      </button>
      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
    </div>
  );
}
