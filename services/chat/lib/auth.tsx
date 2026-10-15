"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { onSessionEnded, refreshSession, signIn, signOut, type SessionUser } from "./session";

interface AuthState {
  user: SessionUser | null;
  loading: boolean;
  login: (username: string, password: string) => Promise<void>;
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

  const logout = async () => {
    await signOut();
    setUser(null);
  };

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
