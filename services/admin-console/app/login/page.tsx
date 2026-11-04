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
import { Labeled } from "@/components/Modal";

const LANDING = "/tickets?view=review";

function Login() {
  const params = useSearchParams();
  const router = useRouter();
  const { user, notStaff } = useAuth();
  const [error, setError] = useState<string | null>(params.get("error"));

  // Redirect once the role check has run: a requester stays here and sees
  // the staff-only notice instead of landing on an empty queue.
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
      <p className="eyebrow">Support console</p>
      <h1 className="font-display text-title font-semibold">Sign in</h1>
      <p className="text-sm text-muted-foreground">For support staff. Use your company account; a manager sets your role and teams.</p>
      {notStaff && (
        <Alert variant="warn" className="text-sm">
          <AlertDescription>
            This console is for support staff. To ask a question or open a ticket, use the IT Help chat.
          </AlertDescription>
        </Alert>
      )}
      <Button size="lg" onClick={() => void signIn()} className="mt-2 h-auto min-h-11 w-full whitespace-normal py-2.5">
        Sign in with company account
      </Button>
      <p lang="vi" className="text-center text-xs text-muted-foreground">Đăng nhập bằng tài khoản công ty</p>
      <p className="border-t border-border pt-3 text-xs text-muted-foreground">
        You&apos;ll go to the company sign-in page, which checks your password and MFA, then come back here.
      </p>
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
      <p className="eyebrow">Support console</p>
      <h1 className="font-display text-title font-semibold">Break-glass sign-in</h1>
      <Alert variant="danger" className="text-xs">
        <AlertDescription>
          Only for the break-glass accounts when company sign-in is down. Every use alerts IT security at once.
        </AlertDescription>
      </Alert>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <Labeled label="Username" required>
          <Input autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
        </Labeled>
        <Labeled label="Password" required>
          <Input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </Labeled>
        {error && (
          <p role="alert" className="text-sm text-danger">
            {error}
          </p>
        )}
        <Button variant="destructive" type="submit" disabled={submitting} className="h-auto min-h-9 w-full whitespace-normal py-2">
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
      <p className="eyebrow !text-danger">Sign-in didn&apos;t finish</p>
      <h1 className="font-display text-xl font-semibold">{text.en}</h1>
      <p lang="vi" className="text-sm text-muted-foreground">{text.vi}</p>
      <Button onClick={onRetry} className="mt-2 h-auto min-h-11 w-full whitespace-normal">
        Try again
      </Button>
      <p className="text-xs text-muted-foreground">
        If it keeps happening, tell IT the code <span className="num rounded-sm bg-muted px-1">{text.code}</span>.
      </p>
    </LoginCard>
  );
}

function LoginCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1fr)_520px]">
      <aside className="hidden flex-col justify-between border-r border-border bg-card p-12 lg:flex">
        <span className="flex items-center gap-2.5">
          <span aria-hidden className="flex size-8 items-center justify-center rounded-md bg-primary font-display font-semibold text-primary-foreground">S</span>
          <span className="font-semibold">Smart Ticket</span>
        </span>
        <div className="max-w-md">
          <p className="font-display text-display font-semibold text-balance">The AI proposes. People decide.</p>
          <ul className="mt-8 flex flex-col gap-4 text-sm">
            <li className="rounded-r-md border-l-2 border-dashed border-proposal py-1 pl-4">
              <span className="eyebrow !text-proposal">Proposal</span>
              <p className="mt-1 text-muted-foreground">Triage reads each ticket and suggests an answer, a team or a question back.</p>
            </li>
            <li className="rounded-r-md border-l-2 border-primary py-1 pl-4">
              <span className="eyebrow !text-primary">Decision</span>
              <p className="mt-1 text-muted-foreground">Fixed rules and reviewers decide what actually happens, and every step is recorded.</p>
            </li>
          </ul>
        </div>
        <p className="text-xs text-muted-foreground">Personal data is masked before any model reads a ticket.</p>
      </aside>
      <main className="flex items-center justify-center px-4 py-12">
        <div className="flex w-full max-w-[380px] flex-col gap-3">{children}</div>
      </main>
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
