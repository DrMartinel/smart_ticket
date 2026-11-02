"use client";

/**
 * Thin fetch wrapper for core-api, the only backend the chat talks to
 * (sign-in is `session.ts`). It
 * never reaches ai-engine: what a requester sees is what core-api decided
 * to show them (`apps/chat`), never a model's raw output.
 */

import type {
  ChatTurnOut,
  InboxOut,
  RatingOut,
  ReopenOut,
  RequesterTicketList,
  RequesterTicketOut,
  ThreadCommentOut,
} from "@/lib/types/generated";
import { accessTokenForRequest, refreshSession, type SessionUser } from "./session";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;
  // core-api's refusal code ({code, message, details}), when it sent one.
  code: string | null;
  constructor(status: number, message: string, code: string | null = null) {
    super(message);
    this.status = status;
    this.code = code;
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
    let code: string | null = null;
    try {
      const body = await resp.json();
      if (typeof body.message === "string") detail = body.message;
      else if (typeof body.detail === "string") detail = body.detail;
      if (typeof body.code === "string") code = body.code;
    } catch {
      // not JSON: keep statusText
    }
    throw new ApiError(resp.status, detail, code);
  }
  if (resp.status === 204) return undefined as T;
  return (await resp.json()) as T;
}

export type CurrentUser = SessionUser;

export const chatApi = {
  history: () => request<ChatTurnOut[]>("/api/chat/tickets"),
  endConversation: (id: string) =>
    request<void>(`/api/chat/conversations/${encodeURIComponent(id)}/end`, { method: "POST" }),
  turn: (publicId: string) => request<ChatTurnOut>(`/api/chat/tickets/${encodeURIComponent(publicId)}`),
  ask: (message: string, conversationId: string | null) =>
    request<ChatTurnOut>("/api/chat/ask", {
      method: "POST",
      body: JSON.stringify(conversationId ? { message, conversation_id: conversationId } : { message }),
    }),
  createTicket: (publicId: string) =>
    request<ChatTurnOut>(`/api/chat/tickets/${encodeURIComponent(publicId)}/create-ticket`, { method: "POST" }),
  clarify: (publicId: string, answer: string) =>
    request<ChatTurnOut>(`/api/chat/tickets/${encodeURIComponent(publicId)}/clarify`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),
};

export const notificationsApi = {
  unread: () => request<InboxOut>("/api/notifications?unread=true&limit=1"),
  recent: (limit = 10) => request<InboxOut>(`/api/notifications?limit=${limit}`),
  read: (id: string) => request<void>(`/api/notifications/${encodeURIComponent(id)}/read`, { method: "POST" }),
  readAll: () => request<void>("/api/notifications/read-all", { method: "POST" }),
};

const ticketPath = (publicId: string) => `/api/requester/tickets/${encodeURIComponent(publicId)}`;

/** The requester's own tickets, form and chat (F3). */
export const requesterApi = {
  list: (before?: string) =>
    request<RequesterTicketList>(`/api/requester/tickets${before ? `?before=${encodeURIComponent(before)}` : ""}`),
  ticket: (publicId: string) => request<RequesterTicketOut>(ticketPath(publicId)),
  reply: (publicId: string, body: string) =>
    request<ThreadCommentOut>(`${ticketPath(publicId)}/replies`, { method: "POST", body: JSON.stringify({ body }) }),
  reopen: (publicId: string, reason: string) =>
    request<ReopenOut>(`${ticketPath(publicId)}/reopen`, { method: "POST", body: JSON.stringify({ reason }) }),
  rate: (publicId: string, score: number, comment: string) =>
    request<RatingOut>(`${ticketPath(publicId)}/rating`, {
      method: "PUT",
      body: JSON.stringify({ score, comment: comment.trim() || null }),
    }),
};
