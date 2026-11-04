"use client";

// Sign-in (F13): the company account through Keycloak; a local password only
// for break-glass accounts (?local=1); a refusal's code and meaning (?error=).

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { startSignIn } from "@/lib/oidc";
import { AuthError } from "@/lib/session";
import { signInError } from "@/lib/signInErrors";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";

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
    <LoginCard>
      <p className="eyebrow">
        Sign in <span lang="vi" className="ml-1 normal-case italic tracking-normal">Đăng nhập</span>
      </p>
      <h1 className="font-display text-title font-semibold">Ask IT, and track what you asked</h1>
      <p className="text-sm text-muted-foreground">
        Answers come from IT&apos;s approved help pages. Anything they don&apos;t cover goes to a person.
      </p>
      <Button size="lg" onClick={() => void signIn()} className="mt-2 h-auto min-h-11 w-full whitespace-normal py-2.5">
        Sign in with your company account
      </Button>
      <p className="text-xs text-muted-foreground">The same sign-in you use for email and VPN.</p>
    </LoginCard>
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
    } catch {
      setError("Invalid username or password, or this isn't a break-glass account.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <LoginCard>
      <p className="eyebrow">Emergency access</p>
      <h1 className="font-display text-title font-semibold">Break-glass sign-in</h1>
      <Alert variant="danger" className="text-xs">
        <AlertDescription>
          Only for the break-glass accounts when company sign-in is down. Every use alerts IT security at once.
        </AlertDescription>
      </Alert>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1.5 text-xs font-medium text-foreground/80">
          Username
          <Input className="text-sm text-foreground" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
        </label>
        <label className="flex flex-col gap-1.5 text-xs font-medium text-foreground/80">
          Password
          <Input
            type="password"
            autoComplete="current-password"
            className="text-sm text-foreground"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <Button variant="destructive" type="submit" disabled={submitting} className="h-auto min-h-10 w-full whitespace-normal py-2">
          {submitting ? "Signing in…" : "Sign in with local account"}
        </Button>
      </form>
    </LoginCard>
  );
}

function SignInError({ code, onRetry }: { code: string; onRetry: () => void }) {
  const text = signInError(code);
  return (
    <LoginCard>
      <p className="eyebrow text-danger">Sign-in didn&apos;t work</p>
      <h1 className="font-display text-title font-semibold">{text.en}</h1>
      <p lang="vi" className="text-sm italic text-muted-foreground">{text.vi}</p>
      <p className="num text-2xs text-muted-foreground">Code: {text.code}</p>
      <Button variant="outline" onClick={onRetry} className="mt-2 h-auto min-h-10 w-full whitespace-normal">
        Try again
      </Button>
    </LoginCard>
  );
}

function LoginCard({ children }: { children: React.ReactNode }) {
  return (
    <main id="main" className="grid min-h-dvh place-items-center px-4 py-10">
      <div className="flex w-full max-w-[420px] flex-col gap-5">
        <div className="flex items-center gap-2.5">
          <span aria-hidden className="flex size-8 items-center justify-center rounded-md bg-primary font-display font-semibold text-primary-foreground">
            S
          </span>
          <span className="font-semibold">IT Help</span>
        </div>
        <section className="flex flex-col gap-3 rounded-md border border-border bg-card p-6 sm:p-8">{children}</section>
      </div>
    </main>
  );
}

export default function LoginPage() {
  return (
    <Suspense>
      <Login />
    </Suspense>
  );
}
