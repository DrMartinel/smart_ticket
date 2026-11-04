"use client";

// Rate the help 1–5 with an optional comment (F3 · Rating 10-623). Changeable until the reopen
// window closes; a low score tells the team lead and never reopens the ticket.

import { useState } from "react";
import { ApiError, requesterApi } from "@/lib/api";
import type { RatingOut } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
          ? "The rating window has closed."
          : "Couldn't save the rating. Try again.",
      );
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-3">
      {!compact && <h2 className="font-medium">How was the help?</h2>}
      <div role="radiogroup" aria-label="Rating" className="-ml-2 flex gap-0.5">
        {[1, 2, 3, 4, 5].map((n) => (
          <button
            key={n}
            role="radio"
            aria-checked={score === n}
            aria-label={`${n} out of 5`}
            onClick={() => setScore(n)}
            className={`flex size-11 items-center justify-center rounded-md text-2xl leading-none transition-colors hover:bg-muted ${n <= score ? "text-proposal" : "text-border-strong"}`}
          >
            {n <= score ? "★" : "☆"}
          </button>
        ))}
      </div>
      <Input
        value={comment}
        onChange={(e) => setComment(e.target.value)}
        maxLength={2000}
        placeholder="Anything to add? (optional)"
        aria-label="Comment"
        className="text-sm"
      />
      <div className="flex flex-wrap items-center gap-3">
        <Button onClick={() => void send()} disabled={busy || score === 0}>
          {busy ? "Saving…" : saved ? "Update rating" : "Send rating"}
        </Button>
        <span className="text-xs text-muted-foreground">
          {saved ? "Saved. " : ""}
          {until ? `You can change it until ${day(until)}.` : ""}
        </span>
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  );
}

export function day(iso: string): string {
  return new Date(iso).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
}
