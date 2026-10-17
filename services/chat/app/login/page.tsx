"use client";

// Sign-in (F13): the company account through Keycloak; a local password only
// for break-glass accounts (?local=1); a refusal's code and meaning (?error=).

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { startSignIn } from "@/lib/oidc";
import { AuthError } from "@/lib/session";
import { signInError } from "@/lib/signInErrors";

const LANDING = "/";

function Login() {
  const params = useSearchParams();
  const router = useRouter();
  const { user } = useAuth();
  const [error, setError] = useState<string | null>(params.get("error"));

  useEffect(() => {
    if (user) router.replace(LANDING);
  }, [user, router]);

  if (params.get("local") === "1") return <BreakGlass />;
  if (error) return <SignInError code={error} onRetry={() => setError(null)} />;

  const signIn = async () => {
    try {
      await startSignIn(LANDING);
    } catch (err) {
      setError(err instanceof AuthError && err.code ? err.code : "idp_unavailable");
    }
  };

  return (
    <Card>
      <h1 className="text-base font-semibold">IT Help</h1>
      <p className="text-xs text-[var(--text-muted)]">Hỏi đáp và tạo phiếu hỗ trợ IT · Ask IT and track your tickets</p>
      <button onClick={() => void signIn()} className="btn btn-primary w-full justify-center py-2.5">
        Đăng nhập bằng tài khoản công ty · Sign in with company account
      </button>
      <p className="text-[11px] text-[var(--text-muted)]">
        Cùng tài khoản đăng nhập với email và VPN · Same company sign-in as email and VPN.
      </p>
    </Card>
  );
}

function BreakGlass() {
  const { login } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);
    try {
      await login(username, password);
    } catch (err) {
      const code = err instanceof AuthError ? err.code : null;
      setError(
        code === "local_login_disabled"
          ? "local_login_disabled: this account signs in with the company account."
          : code === "account_locked"
            ? "account_locked: too many failed passwords. Try again in 15 minutes."
            : "Invalid username or password.",
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Card>
      <h1 className="text-base font-semibold">Break-glass sign-in</h1>
      <p className="tone-danger rounded-[5px] p-3 text-xs">
        Chỉ dành cho tài khoản khẩn cấp · Only for the break-glass accounts when company sign-in is down. Every use alerts IT security at once.
      </p>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-[11px] text-[var(--text-muted)]">
          Username
          <input className="field text-sm text-[var(--text)]" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-[var(--text-muted)]">
          Password
          <input
            type="password"
            className="field text-sm text-[var(--text)]"
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
        <button type="submit" disabled={submitting} className="btn btn-danger w-full justify-center py-2">
          {submitting ? "Signing in…" : "Sign in with local account"}
        </button>
      </form>
    </Card>
  );
}

function SignInError({ code, onRetry }: { code: string; onRetry: () => void }) {
  const text = signInError(code);
  return (
    <Card>
      <span className="badge tone-danger w-full">{text.code}</span>
      <h1 className="text-base font-semibold">{text.vi}</h1>
      <p className="text-xs text-[var(--text-muted)]">{text.en}</p>
      <button onClick={onRetry} className="btn btn-secondary w-full justify-center">
        Thử lại · Try again
      </button>
    </Card>
  );
}

function Card({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh place-items-center px-4">
      <div className="panel flex w-full max-w-[400px] flex-col gap-3 p-8">{children}</div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
