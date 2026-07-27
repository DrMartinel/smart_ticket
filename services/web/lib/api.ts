"use client";

/**
 * Thin fetch wrapper for core-api. core-api is the source of truth (spec
 * §1) — this file is the ONLY place web talks to the backend, and it
 * never talks to ai-engine directly (spec: ai-engine has no routing
 * authority and web never bypasses core-api's RBAC/audit layer).
 */

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
const TOKEN_KEY = "smart_triage_access_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  if (token) window.localStorage.setItem(TOKEN_KEY, token);
  else window.localStorage.removeItem(TOKEN_KEY);
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      const body = await resp.json();
      detail = body.detail ? JSON.stringify(body.detail) : detail;
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(resp.status, detail);
  }

  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: "POST", body: body !== undefined ? JSON.stringify(body) : undefined }),
};

export async function login(username: string, password: string): Promise<{ access: string; refresh: string }> {
  const resp = await fetch(`${API_BASE}/api/token/pair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) {
    throw new ApiError(resp.status, "invalid username or password");
  }
  return resp.json();
}
