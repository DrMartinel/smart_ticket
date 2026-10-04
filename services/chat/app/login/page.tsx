"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { login, setToken } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { SparkleIcon } from "@/components/icons";

export default function LoginPage() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const router = useRouter();
  const { user, refresh } = useAuth();

  useEffect(() => {
    if (user) router.replace("/");
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
      setError("That username and password don't match.");
    } finally {
      setSubmitting(false);
    }
  };

  const field =
    "mt-1.5 w-full rounded-xl border border-[var(--border)] bg-[var(--bg)] px-3.5 py-2.5 text-[15px] outline-none transition focus:border-[var(--accent)]";

  return (
    <div className="grid min-h-dvh place-items-center px-4">
      <div className="turn-in w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="brand-gradient grid h-12 w-12 place-items-center rounded-2xl text-white shadow-lg">
            <SparkleIcon className="h-6 w-6" />
          </div>
          <h1 className="mt-4 text-xl font-semibold tracking-tight">IT Help</h1>
          <p className="mt-1 text-sm text-[var(--text-muted)]">Sign in with your work account.</p>
        </div>
        <form onSubmit={onSubmit} className="surface flex flex-col gap-4 rounded-2xl p-6">
          <label className="text-sm font-medium">
            Username
            <input className={field} value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
          </label>
          <label className="text-sm font-medium">
            Password
            <input
              type="password"
              className={field}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
            />
          </label>
          {error && (
            <p role="alert" className="text-sm text-[var(--danger)]">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="brand-gradient mt-1 rounded-xl px-4 py-2.5 text-sm font-semibold text-white shadow-sm transition hover:brightness-110 disabled:opacity-50"
          >
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
