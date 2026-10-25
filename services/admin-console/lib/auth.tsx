"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { callbackUrl, takePending } from "./oidc";
import { AuthError, exchangeCode, onSessionEnded, refreshSession, signIn, signOut, type SessionUser } from "./session";

export type CurrentUser = SessionUser;

interface AuthState {
  user: CurrentUser | null;
  loading: boolean;
  /** Signed in fine, but as a requester: this console is for staff only. */
  notStaff: boolean;
  login: (username: string, password: string) => Promise<void>;
  /** Finishes a Keycloak sign-in; returns the page to land on. */
  finishSignIn: (code: string, state: string | null) => Promise<string>;
  logout: () => Promise<void>;
}

/** The admin console is for the people who review, route and govern.
 * Requesters use the chat app (services/chat). This hides the console from
 * them; the API's role gates are what actually enforce it. */
const STAFF_ROLES: ReadonlySet<CurrentUser["role"]> = new Set(["technician", "manager", "security"]);

const AuthContext = createContext<AuthState | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [notStaff, setNotStaff] = useState(false);

  /** Keeps a staff member signed in; ends a requester's sign-in at once. */
  const accept = async (signedIn: CurrentUser | null) => {
    if (signedIn && !STAFF_ROLES.has(signedIn.role)) {
      await signOut();
      setUser(null);
      setNotStaff(true);
      return;
    }
    setNotStaff(false);
    setUser(signedIn);
  };

  useEffect(() => {
    const stop = onSessionEnded(() => setUser(null));
    refreshSession()
      .then(accept)
      .finally(() => setLoading(false));
    return stop;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = async (username: string, password: string) => {
    await accept(await signIn(username, password));
  };

  const finishSignIn = async (code: string, state: string | null) => {
    const pending = takePending(state);
    if (!pending) throw new AuthError(400, "state mismatch", "state_mismatch");
    await accept(await exchangeCode(code, pending.verifier, pending.nonce, callbackUrl()));
    return pending.next;
  };

  const logout = async () => {
    await signOut();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, notStaff, login, finishSignIn, logout }}>{children}</AuthContext.Provider>
  );
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

/** Redirects to /login when no authenticated user is present. Renders
 * nothing while the auth check is in flight to avoid a flash of
 * protected content. */
export function useRequireAuth(): CurrentUser | null {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  return user;
}
