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
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";

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
      <h1 className="text-base font-semibold">Smart Ticket · Admin Console</h1>
      <p className="text-xs text-muted-foreground">For support staff. Sign in with your company account; a manager sets your role and teams.</p>
      {notStaff && (
        <Alert variant="warn" className="text-sm">
          <AlertDescription>
            This console is for support staff. To ask a question or open a ticket, use the IT Help chat.
          </AlertDescription>
        </Alert>
      )}
      <Button size="lg" onClick={() => void signIn()} className="h-auto min-h-10 w-full whitespace-normal py-2.5">
        Đăng nhập bằng tài khoản công ty · Sign in with company account
      </Button>
      <p className="text-[11px] text-muted-foreground">
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
      <h1 className="text-base font-semibold">Break-glass sign-in</h1>
      <Alert variant="danger" className="text-xs">
        <AlertDescription>
          Only for the break-glass accounts when company sign-in is down. Every use alerts IT security at once.
        </AlertDescription>
      </Alert>
      <form onSubmit={onSubmit} className="flex flex-col gap-3">
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          Username
          <Input className="text-sm text-foreground" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
        </label>
        <label className="flex flex-col gap-1 text-[11px] text-muted-foreground">
          Password
          <Input
            type="password"
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
      <Badge variant="danger" className="w-full">{text.code}</Badge>
      <h1 className="text-base font-semibold">{text.vi}</h1>
      <p className="text-xs text-muted-foreground">{text.en}</p>
      <Button variant="outline" onClick={onRetry} className="h-auto min-h-9 w-full whitespace-normal">
        Thử lại · Try again
      </Button>
    </LoginCard>
  );
}

function LoginCard({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid min-h-dvh place-items-center px-4">
      <Card className="flex w-full max-w-[400px] flex-col gap-3 p-8">{children}</Card>
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
