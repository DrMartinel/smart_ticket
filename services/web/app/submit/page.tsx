"use client";

import { useState } from "react";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";

interface SubmitResult {
  ticket_public_id: string;
  status: string;
  pii_level: string;
}

export default function SubmitPage() {
  const user = useRequireAuth();
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<SubmitResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  if (!user) return null;

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setResult(null);
    setSubmitting(true);
    try {
      const res = await api.post<SubmitResult>("/api/tickets/submit", { subject, body });
      setResult(res);
      setSubject("");
      setBody("");
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to submit ticket.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="mb-1 text-xl font-semibold">Submit a ticket</h1>
      <p className="mb-6 text-sm text-[var(--text-muted)]">
        Your ticket is masked for PII before anything else happens to it, then triaged automatically. A person
        reviews anything the system isn&apos;t confident about.
      </p>

      <form onSubmit={onSubmit} className="card flex flex-col gap-4 p-5">
        <label className="text-sm">
          Subject
          <input
            className="mt-1 w-full rounded border px-3 py-2 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--bg)" }}
            value={subject}
            onChange={(e) => setSubject(e.target.value)}
            minLength={3}
            maxLength={200}
            required
            placeholder="Không đăng nhập được máy tính"
          />
        </label>
        <label className="text-sm">
          Description
          <textarea
            className="mt-1 w-full rounded border px-3 py-2 text-sm"
            style={{ borderColor: "var(--border)", background: "var(--bg)" }}
            rows={6}
            value={body}
            onChange={(e) => setBody(e.target.value)}
            minLength={10}
            maxLength={10000}
            required
            placeholder="Describe the issue in as much detail as you can..."
          />
        </label>
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className="self-start rounded bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
        >
          {submitting ? "Submitting…" : "Submit ticket"}
        </button>
      </form>

      {result && (
        <div className="card mt-4 p-4 text-sm">
          <p className="font-medium text-emerald-700 dark:text-emerald-400">Ticket submitted: {result.ticket_public_id}</p>
          <p className="mt-1 text-[var(--text-muted)]">
            Status: {result.status} · PII level detected: {result.pii_level}
          </p>
          <p className="mt-2 text-[var(--text-muted)]">
            It&apos;s being triaged now — a technician will follow up if it needs a human look.
          </p>
        </div>
      )}
    </div>
  );
}
