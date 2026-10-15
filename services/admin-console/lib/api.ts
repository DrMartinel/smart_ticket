"use client";

/**
 * Thin fetch wrapper for core-api. core-api is the source of truth (spec
 * §1) — this file and `session.ts` (sign-in) are the ONLY places web talks
 * to the backend, and they
 * never talks to ai-engine directly (spec: ai-engine has no routing
 * authority and web never bypasses core-api's RBAC/audit layer).
 */

import { accessTokenForRequest, refreshSession } from "./session";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, options: RequestInit = {}, retried = false): Promise<T> {
  const token = await accessTokenForRequest();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });

  // An access token can expire or be revoked between the check and the call: refresh once.
  if (resp.status === 401 && !retried && (await refreshSession())) {
    return request<T>(path, options, true);
  }

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
