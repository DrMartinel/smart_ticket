"use client";

// "Still not fixed": reopen within 7 days, else a new ticket linked to this one (UC-F3-04).

import Link from "next/link";
import { useState } from "react";
import { ApiError, requesterApi } from "@/lib/api";
import type { ReopenOut } from "@/lib/types/generated";
import { day } from "./Rating";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

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
          ? "Say what still doesn't work."
          : "Couldn't reopen it. Try again in a moment.",
      );
    } finally {
      setBusy(false);
    }
  };

  if (result) {
    return result.reopened ? (
      <p role="status" className="text-sm">Reopened. A person on the support team will take it from here.</p>
    ) : (
      <p role="status" className="text-sm">
        A new ticket{" "}
        <Link href={`/tickets/${result.new_ticket}`} className="num text-primary underline">
          {result.new_ticket}
        </Link>{" "}
        is linked to this one.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      <p className="text-xs text-muted-foreground">
        {until && !late
          ? `You can reopen it until ${day(until)}. After that we open a new ticket linked to this one.`
          : "It's been more than 7 days, so we'll open a new ticket linked to this one."}
      </p>
      <Textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        maxLength={2000}
        placeholder="What still doesn't work?"
        aria-label="Why it isn't solved"
        className="min-h-[64px] text-sm"
      />
      <Button variant="outline" onClick={() => void send()} disabled={busy || !reason.trim()} className="self-start">
        {late ? "Open a new linked ticket" : "Reopen ticket"}
      </Button>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  );
}
