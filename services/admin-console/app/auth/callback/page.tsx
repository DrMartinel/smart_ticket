"use client";

// Where Keycloak sends the browser back: swaps the code for a session (F13).

import { Suspense, useEffect, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/lib/auth";
import { AuthError } from "@/lib/session";

function Callback() {
  const params = useSearchParams();
  const router = useRouter();
  const { finishSignIn } = useAuth();
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const code = params.get("code");
    if (!code) {
      router.replace("/login?error=keycloak_error");
      return;
    }
    finishSignIn(code, params.get("state"))
      .then((next) => router.replace(next || "/tickets?view=review"))
      .catch((err) => router.replace(`/login?error=${err instanceof AuthError && err.code ? err.code : "oidc_token_invalid"}`));
  }, [params, router, finishSignIn]);

  return (
    <p role="status" className="mt-24 flex items-center justify-center gap-2 text-sm text-muted-foreground">
      <span aria-hidden className="size-3 animate-pulse rounded-full bg-primary" /> Signing you in…
    </p>
  );
}

export default function CallbackPage() {
  return (
    <Suspense>
      <Callback />
    </Suspense>
  );
}
