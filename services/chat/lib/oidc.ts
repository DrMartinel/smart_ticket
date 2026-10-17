"use client";

/**
 * The browser half of the Keycloak sign-in (F13): PKCE (S256), state and
 * nonce. The verifier, state and nonce live in sessionStorage only for the
 * round trip to Keycloak and are removed when the callback reads them; no
 * token is ever stored.
 */

import { AuthError } from "./session";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const PENDING_KEY = "smart_ticket_oidc_pending";

interface OidcConfig {
  authorize_url: string;
  client_id: string;
  scopes: string;
}

interface Pending {
  verifier: string;
  state: string;
  nonce: string;
  next: string;
}

export function callbackUrl(): string {
  return `${window.location.origin}/auth/callback`;
}

/** Sends the browser to Keycloak; `next` is where to land after signing in. */
export async function startSignIn(next: string): Promise<void> {
  const resp = await fetch(`${API_BASE}/api/auth/oidc/config`, { cache: "no-store" });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    throw new AuthError(resp.status, body.message ?? "sign-in is unavailable", body.code ?? "idp_unavailable");
  }
  const config = (await resp.json()) as OidcConfig;
  const pending: Pending = { verifier: randomString(48), state: randomString(24), nonce: randomString(24), next };
  sessionStorage.setItem(PENDING_KEY, JSON.stringify(pending));
  const params = new URLSearchParams({
    client_id: config.client_id,
    response_type: "code",
    scope: config.scopes,
    redirect_uri: callbackUrl(),
    state: pending.state,
    nonce: pending.nonce,
    code_challenge: await challenge(pending.verifier),
    code_challenge_method: "S256",
  });
  window.location.assign(`${config.authorize_url}?${params}`);
}

/** The round trip's verifier and nonce if `state` matches, removed either way. */
export function takePending(state: string | null): Pending | null {
  const raw = sessionStorage.getItem(PENDING_KEY);
  sessionStorage.removeItem(PENDING_KEY);
  if (!raw || !state) return null;
  const pending = JSON.parse(raw) as Pending;
  return pending.state === state ? pending : null;
}

function randomString(bytes: number): string {
  return base64url(crypto.getRandomValues(new Uint8Array(bytes)));
}

async function challenge(verifier: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier));
  return base64url(new Uint8Array(digest));
}

function base64url(bytes: Uint8Array): string {
  let text = "";
  bytes.forEach((b) => (text += String.fromCharCode(b)));
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
