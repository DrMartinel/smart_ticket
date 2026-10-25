"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const router = useRouter();
  const { user, notStaff, login } = useAuth();

  // Redirect once the role check has run: a requester stays here and sees
  // the staff-only notice instead of landing on an empty queue.
  useEffect(() => {
    if (user) router.replace("/tickets?view=review");
  }, [user, router]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
    } catch {
      setError("Invalid username or password.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mx-auto mt-24 max-w-sm">
      <h1 className="text-xl font-semibold">Smart Ticket</h1>
      <p className="mt-1 text-sm text-[var(--text-muted)]">Support console. Sign in with your staff account.</p>
      {notStaff && (
        <p className="tone-warn mt-4 rounded-[5px] p-3 text-sm">
          This console is for support staff. To ask a question or open a ticket, use the IT Help chat.
        </p>
      )}
      <form onSubmit={onSubmit} className="card mt-6 flex flex-col gap-4 p-5">
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Username
          <input className="field font-normal" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-medium">
          Password
          <input
            type="password"
            className="field font-normal"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
        <button type="submit" disabled={submitting} className="btn btn-primary mt-1 justify-center py-2">
          {submitting ? "Signing in…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}
