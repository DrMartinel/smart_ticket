"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRequireAuth } from "@/lib/auth";
import { api } from "@/lib/api";
import { priorityClasses } from "@/lib/badges";

interface QueueItem {
  id: number;
  ticket_public_id: string;
  subject_masked: string;
  queue: string;
  priority: number;
  state: string;
  created_at: string;
  trust_score: number | null;
  routing_decisions: { branch: string; reason_code: string }[];
}

const QUEUES = ["", "pii_verify", "low_confidence", "injection", "mask_failed", "runbook_approval"];

export default function QueuePage() {
  const user = useRequireAuth();
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [queueFilter, setQueueFilter] = useState("");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    setItems(null);
    const path = queueFilter ? `/api/review/queue?queue=${queueFilter}` : "/api/review/queue";
    api
      .get<QueueItem[]>(path)
      .then(setItems)
      .catch(() => setError("Failed to load the review queue."));
  }, [user, queueFilter]);

  if (!user) return null;

  return (
    <div>
      <div className="mb-4 flex items-center justify-between">
        <h1 className="text-xl font-semibold">Review queue</h1>
        <select
          className="rounded border px-2 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", background: "var(--bg)" }}
          value={queueFilter}
          onChange={(e) => setQueueFilter(e.target.value)}
        >
          <option value="">All queues</option>
          {QUEUES.filter(Boolean).map((q) => (
            <option key={q} value={q}>
              {q}
            </option>
          ))}
        </select>
      </div>

      {error && <p className="text-sm text-red-600">{error}</p>}
      {items === null && !error && <p className="text-sm text-[var(--text-muted)]">Loading…</p>}
      {items !== null && items.length === 0 && (
        <p className="text-sm text-[var(--text-muted)]">Nothing pending — the queue is empty.</p>
      )}

      <div className="flex flex-col gap-2">
        {items?.map((item) => (
          <Link
            key={item.id}
            href={`/review/${item.id}`}
            className="card flex items-center justify-between p-3 text-sm transition hover:border-[var(--accent)]"
          >
            <div className="flex items-center gap-3">
              <span className={`badge ${priorityClasses(item.priority)}`}>P{item.priority}</span>
              <div>
                <div className="font-medium">{item.subject_masked}</div>
                <div className="text-xs text-[var(--text-muted)]">
                  {item.ticket_public_id} · {item.queue}
                </div>
              </div>
            </div>
            <div className="text-right text-xs text-[var(--text-muted)]">
              {item.trust_score !== null && <div>trust {item.trust_score.toFixed(2)}</div>}
              <div>{new Date(item.created_at).toLocaleString()}</div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
