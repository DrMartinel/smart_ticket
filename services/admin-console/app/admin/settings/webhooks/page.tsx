"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState, TableStatus } from "@/components/ui/states";

// Webhook subscriptions (F4 · 11-1047): signed JSON to allow-listed hosts only.

import { useCallback, useEffect, useState } from "react";
import Switch from "@/components/Switch";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { MatrixCellOut, WebhookIn, WebhookOut } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { SectionTabs } from "@/components/TabNav";

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
    <Page width="record" className="flex flex-col gap-4">
      <SectionTabs className="mb-1" />
      <PageHeader
        className="mb-2"
        eyebrow="Admin / Notifications"
        title="Webhook subscriptions"
        description={<>Signed JSON (HMAC-SHA256 in X-SmartTicket-Signature) to allow-listed hosts only, the same check as the call_webhook action.</>}
        actions={
      <>
      {!draft && (
        <Button onClick={() => setDraft({ ...EMPTY, secret: newSecret() })}>
          New subscription
        </Button>
      )}
      </>
      }
      />

      {error && <ErrorState title={error} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[860px] text-xs">
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>URL</TableHead>
              <TableHead>Events</TableHead>
              <TableHead>Active</TableHead>
              <TableHead>Created by</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {hooks?.map((hook) => (
              <TableRow key={hook.id}>
                <TableCell>{hook.name}</TableCell>
                <TableCell className="num break-all">{hook.url}</TableCell>
                <TableCell>{hook.events.join(", ")}</TableCell>
                <TableCell>
                  <Switch checked={hook.is_active} label={`${hook.name} active`} onChange={(next) => void setActive(hook, next)} />
                </TableCell>
                <TableCell>{hook.created_by}</TableCell>
                <TableCell className="text-right">
                  <Button variant="link" size="inline" className="text-xs text-danger" onClick={() => void remove(hook)}>
                    Delete
                  </Button>
                </TableCell>
              </TableRow>
            ))}
            <TableStatus colSpan={6} rows={hooks} error={!!error} empty={<EmptyState compact title="No subscriptions yet" />} />
          </TableBody>
        </Table>
      </Card>

      {draft && (
        <Card asChild>
          <form
            className="flex flex-col gap-3 p-4"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <h2 className="text-sm font-semibold">New subscription</h2>
            <div className="flex flex-wrap gap-3">
              <label className="flex w-[240px] flex-col gap-1">
                <span className="text-xs font-medium text-foreground/80">Name</span>
                <Input required maxLength={100} value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </label>
              <label className="flex min-w-[280px] flex-1 flex-col gap-1">
                <span className="text-xs font-medium text-foreground/80">URL</span>
                <Input required type="url" maxLength={500} value={draft.url} onChange={(e) => setDraft({ ...draft, url: e.target.value })} placeholder="https://n8n.example/webhook/…" />
              </label>
            </div>
            <fieldset className="flex flex-col gap-1">
              <legend className="text-[11px] text-muted-foreground">Events</legend>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5 pt-1">
                {events.map(({ event, active }) => (
                  <label key={event} className={`flex items-center gap-1.5 text-xs ${active ? "" : "text-muted-foreground"}`}>
                    <Checkbox checked={draft.events.includes(event)} onCheckedChange={() => toggleEvent(event)} />
                    <span className="font-mono">{event}</span>
                  </label>
                ))}
              </div>
            </fieldset>
            <label className="flex max-w-[640px] flex-col gap-1">
              <span className="text-xs font-medium text-foreground/80">Signing secret: copy it now, it is never shown again</span>
              <Input required minLength={16} maxLength={200} value={draft.secret} onChange={(e) => setDraft({ ...draft, secret: e.target.value })} className="font-mono" />
            </label>
            {formError && <p className="rounded-md bg-danger-soft px-3 py-2 text-sm text-danger">{formError}</p>}
            <div className="flex gap-2">
              <Button variant="outline" type="button" onClick={() => (setDraft(null), setFormError(null))}>
                Cancel
              </Button>
              <Button type="submit" disabled={draft.events.length === 0}>
                Save
              </Button>
            </div>
          </form>
        </Card>
      )}
    </Page>
  );
}
