"use client";

/**
 * Thin fetch wrapper for core-api, the only backend the chat talks to. It
 * never reaches ai-engine: what a requester sees is what core-api decided
 * to show them (`apps/chat`), never a model's raw output.
 */

import type { ChatTurnOut } from "@/lib/types/generated";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";
// Separate from the admin console's key: both apps can run on localhost.
const TOKEN_KEY = "smart_ticket_chat_access_token";

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (token) window.localStorage.setItem(TOKEN_KEY, token);
    else window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // storage blocked: the session lasts as long as the page
  }
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
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // not JSON: keep statusText
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

export interface CurrentUser {
  id: string;
  username: string;
  email: string;
  role: string;
}

export const chatApi = {
  me: () => request<CurrentUser>("/api/accounts/me"),
  history: () => request<ChatTurnOut[]>("/api/chat/tickets"),
  turn: (publicId: string) => request<ChatTurnOut>(`/api/chat/tickets/${encodeURIComponent(publicId)}`),
  ask: (message: string) =>
    request<ChatTurnOut>("/api/chat/ask", { method: "POST", body: JSON.stringify({ message }) }),
  createTicket: (publicId: string) =>
    request<ChatTurnOut>(`/api/chat/tickets/${encodeURIComponent(publicId)}/create-ticket`, { method: "POST" }),
};

export async function login(username: string, password: string): Promise<{ access: string }> {
  const resp = await fetch(`${API_BASE}/api/token/pair`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ username, password }),
  });
  if (!resp.ok) throw new ApiError(resp.status, "invalid username or password");
  return resp.json();
}
