"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { login, setToken } from "@/lib/api";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const router = useRouter();
  const { user, notStaff, refresh } = useAuth();

  // Redirect once the role check has run: a requester stays here and sees
  // the staff-only notice instead of landing on an empty queue.
  useEffect(() => {
    if (user) router.replace("/queue");
  }, [user, router]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      const { access } = await login(username, password);
      setToken(access);
      await refresh();
    } catch {
      setError("Invalid username or password.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto mt-24 max-w-sm">
      <div className="card p-6">
        <h1 className="mb-1 text-lg font-semibold">Smart Ticket · Admin Console</h1>
        <p className="mb-6 text-sm text-[var(--text-muted)]">For support staff. Sign in to continue.</p>
        {notStaff && (
          <p className="mb-4 rounded border p-3 text-sm" style={{ borderColor: "var(--border)" }}>
            This console is for support staff. To ask a question or open a ticket, use the help chat.
          </p>
        )}
        <form onSubmit={onSubmit} className="flex flex-col gap-3">
          <label className="text-sm">
            Username
            <input
              className="mt-1 w-full rounded border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--bg)" }}
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoFocus
              required
            />
          </label>
          <label className="text-sm">
            Password
            <input
              type="password"
              className="mt-1 w-full rounded border px-3 py-2 text-sm"
              style={{ borderColor: "var(--border)", background: "var(--bg)" }}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button
            type="submit"
            disabled={submitting}
            className="mt-2 rounded bg-[var(--accent)] px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
          >
            {submitting ? "Signing in..." : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
