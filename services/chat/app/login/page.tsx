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
  const { user, login } = useAuth();

  useEffect(() => {
    if (user) router.replace("/");
  }, [user, router]);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
    } catch {
      setError("That username and password don't match.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="grid min-h-dvh place-items-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-xl font-semibold">IT Help</h1>
        <p className="mt-1 text-sm text-[var(--text-muted)]">Sign in with your work account to ask IT a question.</p>
        <form onSubmit={onSubmit} className="panel mt-6 flex flex-col gap-4 p-5">
          <label className="flex flex-col gap-1.5 text-sm font-medium">
            Username
            <input className="field text-[15px] font-normal" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
          </label>
          <label className="flex flex-col gap-1.5 text-sm font-medium">
            Password
            <input
              type="password"
              className="field text-[15px] font-normal"
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
          <button type="submit" disabled={submitting} className="btn btn-primary mt-1 justify-center py-2.5">
            {submitting ? "Signing in…" : "Sign in"}
          </button>
        </form>
      </div>
    </div>
  );
}
