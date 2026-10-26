"use client";

// Rate the help 1–5 with an optional comment (F3 · Rating 10-623). Changeable until the reopen
// window closes; a low score tells the team lead and never reopens the ticket.

import { useState } from "react";
import { ApiError, requesterApi } from "@/lib/api";
import type { RatingOut } from "@/lib/types/generated";

export default function Rating({
  publicId,
  current,
  until,
  compact = false,
}: {
  publicId: string;
  current: RatingOut | null;
  until: string | null;
  compact?: boolean;
}) {
  const [score, setScore] = useState(current?.score ?? 0);
  const [comment, setComment] = useState(current?.comment_masked ?? "");
  const [saved, setSaved] = useState<RatingOut | null>(current);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      setSaved(await requesterApi.rate(publicId, score, comment));
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === "rating_window_closed"
          ? "Đã hết hạn đánh giá · The rating window has closed."
          : "Không gửi được · Couldn't save the rating.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {!compact && <h2 className="font-medium">Bạn thấy hỗ trợ thế nào? · How was the help?</h2>}
      <div role="radiogroup" aria-label="Rating" className="flex gap-1">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            role="radio"
            aria-checked={score === n}
            aria-label={`${n} / 5`}
            onClick={() => setScore(n)}
            className={`text-2xl leading-none ${n <= score ? "text-[var(--warn)]" : "text-[var(--border-strong)]"}`}
          >
            {n <= score ? "★" : "☆"}
          </button>
        ))}
      </div>
      <input
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        maxLength={2000}
        placeholder="Góp ý thêm (không bắt buộc) · Comment (optional)"
        aria-label="Comment"
        className="field text-sm"
      />
      <div className="flex flex-wrap items-center gap-3">
        <button onClick={() => void send()} disabled={busy || score === 0} className="btn btn-primary">
          {saved ? "Cập nhật · Update" : "Gửi đánh giá · Send"}
        </button>
        <span className="text-xs text-[var(--text-muted)]">
          {saved ? "Đã lưu · Saved. " : ""}
          {until ? `You can change it until ${day(until)}.` : ""}
        </span>
      </div>
      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
    </div>
  );
}

export function day(iso: string): string {
  return new Date(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}
