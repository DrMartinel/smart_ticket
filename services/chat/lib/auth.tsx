"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { callbackUrl, takePending } from "./oidc";
import { AuthError, exchangeCode, onSessionEnded, refreshSession, signIn, signOut, type SessionUser } from "./session";

interface AuthState {
  user: SessionUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
  /** Finishes a Keycloak sign-in; returns the page to land on. */
  finishSignIn: (code: string, state: string | null) => Promise<string>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const stop = onSessionEnded(() => setUser(null));
    refreshSession()
      .then(setUser)
      .finally(() => setLoading(false));
    return stop;
  }, []);

  const login = async (username: string, password: string) => {
    setUser(await signIn(username, password));
  };

  const finishSignIn = async (code: string, state: string | null) => {
    const pending = takePending(state);
    if (!pending) throw new AuthError(400, "state mismatch", "state_mismatch");
    setUser(await exchangeCode(code, pending.verifier, pending.nonce, callbackUrl()));
    return pending.next;
  };

  const logout = async () => {
    await signOut();
    setUser(null);
  };

  return <AuthContext.Provider value={{ user, loading, login, finishSignIn, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
