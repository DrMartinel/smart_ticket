"use client";

// Webhook subscriptions (F4 · 11-1047): signed JSON to allow-listed hosts only.

import { useCallback, useEffect, useState } from "react";
import Switch from "@/components/Switch";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { MatrixCellOut, WebhookIn, WebhookOut } from "@/lib/types/generated";

const EMPTY: WebhookIn = { name: "", url: "", events: [], secret: "" };

function newSecret(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(24));
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

function refusal(err: unknown): string {
  if (!(err instanceof ApiError)) return "Couldn't save the subscription.";
  if (err.code === "webhook_host_refused") return `${err.message}. Ask for the host to be added to LIFECYCLE_WEBHOOK_ALLOWED_HOSTS.`;
  if (err.code === "unknown_event") return "One of the events isn't in the catalog.";
  if (err.status === 403) return "Only a workflow admin manages webhooks.";
  return err.message;
}

export default function WebhooksPage() {
  const user = useRequireAuth();
  const [hooks, setHooks] = useState<WebhookOut[] | null>(null);
  const [events, setEvents] = useState<{ event: string; active: boolean }[]>([]);
  const [draft, setDraft] = useState<WebhookIn | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setHooks(await api.get<WebhookOut[]>("/api/notifications/webhooks"));
    } catch (err) {
      setError(refusal(err));
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    void load();
    api
      .get<MatrixCellOut[]>("/api/notifications/matrix")
      .then((cells) => {
        const seen = new Map<string, boolean>();
        for (const c of cells) seen.set(c.event, c.active);
        setEvents([...seen].map(([event, active]) => ({ event, active })));
      })
      .catch(() => undefined);
  }, [user, load]);

  if (!user) return null;

  const save = async () => {
    if (!draft) return;
    setFormError(null);
    try {
      await api.post<WebhookOut>("/api/notifications/webhooks", draft);
      setDraft(null);
      await load();
    } catch (err) {
      setFormError(refusal(err));
    }
  };

  const setActive = async (hook: WebhookOut, is_active: boolean) => {
    try {
      await api.patch<WebhookOut>(`/api/notifications/webhooks/${hook.id}`, { is_active });
      await load();
    } catch (err) {
      setError(refusal(err));
    }
  };

  const remove = async (hook: WebhookOut) => {
    if (!window.confirm(`Delete the subscription “${hook.name}” and its delivery history?`)) return;
    try {
      await api.delete<void>(`/api/notifications/webhooks/${hook.id}`);
      await load();
    } catch (err) {
      setError(refusal(err));
    }
  };

  const toggleEvent = (event: string) =>
    draft && setDraft({ ...draft, events: draft.events.includes(event) ? draft.events.filter((e) => e !== event) : [...draft.events, event] });

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Webhook subscriptions</h1>
          <p className="text-xs text-[var(--text-muted)]">
            Signed JSON (HMAC-SHA256 in X-SmartTicket-Signature) to allow-listed hosts only, the same check as the call_webhook action.
          </p>
        </div>
        {!draft && (
          <button className="btn btn-primary" onClick={() => setDraft({ ...EMPTY, secret: newSecret() })}>
            New subscription
          </button>
        )}
      </header>

      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[860px] text-left text-xs">
          <thead className="bg-[var(--bg)] text-[11px] text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2 font-normal">Name</th>
              <th className="px-4 py-2 font-normal">URL</th>
              <th className="px-4 py-2 font-normal">Events</th>
              <th className="px-4 py-2 font-normal">Active</th>
              <th className="px-4 py-2 font-normal">Created by</th>
              <th className="px-4 py-2 font-normal" />
            </tr>
          </thead>
          <tbody>
            {hooks?.map((hook) => (
              <tr key={hook.id} className="border-t border-[var(--border)]">
                <td className="px-4 py-2.5">{hook.name}</td>
                <td className="px-4 py-2.5 font-mono break-all">{hook.url}</td>
                <td className="px-4 py-2.5">{hook.events.join(", ")}</td>
                <td className="px-4 py-2.5">
                  <Switch checked={hook.is_active} label={`${hook.name} active`} onChange={(next) => void setActive(hook, next)} />
                </td>
                <td className="px-4 py-2.5">{hook.created_by}</td>
                <td className="px-4 py-2.5 text-right">
                  <button className="text-xs text-[var(--danger)] hover:underline" onClick={() => void remove(hook)}>
                    Delete
                  </button>
                </td>
              </tr>
            ))}
            {hooks?.length === 0 && (
              <tr>
                <td colSpan={6} className="px-4 py-6 text-center text-[var(--text-muted)]">
                  No subscriptions yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {draft && (
        <form
          className="card flex flex-col gap-3 p-4"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <h2 className="text-sm font-semibold">New subscription</h2>
          <div className="flex flex-wrap gap-3">
            <label className="flex w-[240px] flex-col gap-1">
              <span className="text-[11px] text-[var(--text-muted)]">Name</span>
              <input required maxLength={100} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} className="field" />
            </label>
            <label className="flex min-w-[280px] flex-1 flex-col gap-1">
              <span className="text-[11px] text-[var(--text-muted)]">URL</span>
              <input required type="url" maxLength={500} value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })} className="field" placeholder="https://n8n.example/webhook/…" />
            </label>
          </div>
          <fieldset className="flex flex-col gap-1">
            <legend className="text-[11px] text-[var(--text-muted)]">Events</legend>
            <div className="flex flex-wrap gap-x-4 gap-y-1.5 pt-1">
              {events.map(({ event, active }) => (
                <label key={event} className={`flex items-center gap-1.5 text-xs ${active ? "" : "text-[var(--text-muted)]"}`}>
                  <input type="checkbox" checked={draft.events.includes(event)} onChange={() => toggleEvent(event)} />
                  <span className="font-mono">{event}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <label className="flex max-w-[640px] flex-col gap-1">
            <span className="text-[11px] text-[var(--text-muted)]">Signing secret: copy it now, it is never shown again</span>
            <input required minLength={16} maxLength={200} value={draft.secret} onChange={(e) => setDraft({ ...draft, secret: e.target.value })} className="field font-mono" />
          </label>
          {formError && <p className="rounded-[5px] bg-[var(--danger-soft)] px-3 py-2 text-sm text-[var(--danger)]">{formError}</p>}
          <div className="flex gap-2">
            <button type="button" className="btn btn-secondary" onClick={() => (setDraft(null), setFormError(null))}>
              Cancel
            </button>
            <button type="submit" className="btn btn-primary" disabled={draft.events.length === 0}>
              Save
            </button>
          </div>
        </form>
      )}
    </div>
  );
}
