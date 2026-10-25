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
  code: string | null;
  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function authedFetch(path: string, options: RequestInit = {}, retried = false): Promise<Response> {
  const token = await accessTokenForRequest();
  const headers = new Headers(options.headers);
  headers.set("Content-Type", "application/json");
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const resp = await fetch(`${API_BASE}${path}`, { ...options, headers });

  // An access token can expire or be revoked between the check and the call: refresh once.
  if (resp.status === 401 && !retried && (await refreshSession())) {
    return authedFetch(path, options, true);
  }

  if (!resp.ok) {
    let detail = resp.statusText;
    let code: string | null = null;
    try {
      const body = await resp.json();
      if (typeof body.code === "string") code = body.code;
      if (typeof body.message === "string") detail = body.message;
      else if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail)) detail = body.detail.map((d: { msg?: string }) => d.msg).join("; ");
    } catch {
      // response wasn't JSON — keep statusText
    }
    throw new ApiError(resp.status, detail, code);
  }
  return resp;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const resp = await authedFetch(path, options);
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

/** A signed-in GET whose body is a file, e.g. a CSV export. */
export async function download(path: string): Promise<Blob> {
  return (await authedFetch(path, { method: "GET", cache: "no-store" })).blob();
}

const send =
  (method: string) =>
  <T>(path: string, body?: unknown) =>
    request<T>(path, { method, body: body !== undefined ? JSON.stringify(body) : undefined });

export const api = {
  get: <T>(path: string) => request<T>(path, { method: "GET" }),
  post: send("POST"),
  patch: send("PATCH"),
  put: send("PUT"),
  delete: send("DELETE"),
};
