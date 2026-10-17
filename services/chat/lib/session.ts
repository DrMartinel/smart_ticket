"use client";

/**
 * The sign-in session (core-api ADR-0029). The access token lives only in
 * this module's memory, never in storage a script can read later. The
 * refresh token is an httpOnly cookie the browser sends to /api/auth/ only;
 * no code here can read it. A page load restores the session by refreshing.
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const CLIENT = "chat";
// Refresh this long before the access token expires.
const REFRESH_EARLY_MS = 30_000;
// Never schedule a refresh sooner than this, however short the token.
const MIN_REFRESH_DELAY_MS = 5_000;
// Earlier builds kept the access token here; removed on load.
const LEGACY_TOKEN_KEY = "smart_ticket_chat_access_token";

export interface SessionUser {
  id: string;
  username: string;
  email: string;
  role: "employee" | "technician" | "manager" | "security";
  auth_source?: "local" | "oidc";
  language?: "vi" | "en";
  capabilities?: string[];
  teams?: { team: string; role: "member" | "lead" }[];
}

interface SessionOut {
  access: string;
  access_expires_at: string;
  user: SessionUser;
}

let accessToken: string | null = null;
let accessExpiresAt = 0;
let refreshTimer: ReturnType<typeof setTimeout> | null = null;
let inFlight: Promise<SessionUser | null> | null = null;
const endListeners = new Set<() => void>();

const channel: BroadcastChannel | null =
  typeof window !== "undefined" && "BroadcastChannel" in window
    ? new BroadcastChannel(`smart-triage-auth-${CLIENT}`)
    : null;

if (typeof window !== "undefined") {
  try {
    window.localStorage.removeItem(LEGACY_TOKEN_KEY);
  } catch {
    // storage blocked: nothing to clean up
  }
}

channel?.addEventListener("message", (event: MessageEvent) => {
  if (event.data === "logout") endLocally();
});

export class AuthError extends Error {
  status: number;
  code: string | null;
  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

/** The access token to send, refreshed first when missing or about to expire. */
export async function accessTokenForRequest(): Promise<string | null> {
  if (accessToken && accessExpiresAt - Date.now() > MIN_REFRESH_DELAY_MS) return accessToken;
  await refreshSession();
  return accessToken;
}

/** Swaps the refresh cookie for a new access token; one request at a time, shared by callers. */
export function refreshSession(): Promise<SessionUser | null> {
  inFlight ??= (async () => {
    try {
      const resp = await authPost("/api/auth/refresh");
      if (!resp.ok) {
        endLocally();
        return null;
      }
      return adopt((await resp.json()) as SessionOut);
    } catch {
      return null;
    } finally {
      inFlight = null;
    }
  })();
  return inFlight;
}

/** Break-glass sign-in with a local password (F13); everyone else uses `exchangeCode`. */
export async function signIn(username: string, password: string): Promise<SessionUser> {
  const resp = await authPost("/api/auth/login", { username, password });
  if (!resp.ok) throw await refusal(resp, "invalid username or password");
  return adopt((await resp.json()) as SessionOut);
}

/** Swaps Keycloak's one-time code for a core-api session (F13). */
export async function exchangeCode(code: string, codeVerifier: string, nonce: string, redirectUri: string): Promise<SessionUser> {
  const resp = await authPost("/api/auth/oidc/exchange", {
    code,
    code_verifier: codeVerifier,
    nonce,
    redirect_uri: redirectUri,
  });
  if (!resp.ok) throw await refusal(resp, "sign-in was refused");
  return adopt((await resp.json()) as SessionOut);
}

async function refusal(resp: Response, fallback: string): Promise<AuthError> {
  try {
    const body = await resp.json();
    return new AuthError(resp.status, body.message ?? body.detail ?? fallback, body.code ?? null);
  } catch {
    return new AuthError(resp.status, fallback);
  }
}

/** Ends this sign-in on the server and in every open tab of this app. */
export async function signOut(): Promise<void> {
  try {
    await authPost("/api/auth/logout");
  } finally {
    endLocally();
    channel?.postMessage("logout");
  }
}

/** Calls `listener` whenever the session ends: signed out, refused, or expired. */
export function onSessionEnded(listener: () => void): () => void {
  endListeners.add(listener);
  return () => endListeners.delete(listener);
}

function adopt(session: SessionOut): SessionUser {
  accessToken = session.access;
  accessExpiresAt = Date.parse(session.access_expires_at);
  if (refreshTimer) clearTimeout(refreshTimer);
  const delay = Math.max(accessExpiresAt - Date.now() - REFRESH_EARLY_MS, MIN_REFRESH_DELAY_MS);
  refreshTimer = setTimeout(() => void refreshSession(), delay);
  return session.user;
}

function endLocally() {
  const hadSession = accessToken !== null;
  accessToken = null;
  accessExpiresAt = 0;
  if (refreshTimer) clearTimeout(refreshTimer);
  refreshTimer = null;
  if (hadSession) endListeners.forEach((listener) => listener());
}

function authPost(path: string, body?: unknown): Promise<Response> {
  return fetch(`${API_BASE}${path}`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json", "X-Auth-Client": CLIENT },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}
