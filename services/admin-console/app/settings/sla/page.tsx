"use client";

// SLA policies (F1 · SLA policies 8-57): targets in business minutes, drafted by a workflow admin,
// activated by another manager; and a preview of due times.

import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { PriorityChip } from "@/components/SlaBadge";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { CalendarOut, PolicyIn, PolicyOut, PreviewIn, PreviewOut, Priority, TicketCategory } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge, type Tone } from "@/components/ui/badge";
import { NativeSelect } from "@/components/ui/native-select";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";

const CATEGORIES: TicketCategory[] = ["hardware", "software", "network", "access", "security", "other"];
const PRIORITIES: Priority[] = ["P1", "P2", "P3", "P4"];

function minutesText(m: number, roundTheClock = false): string {
  if (roundTheClock) return m % 60 === 0 && m >= 60 ? `${m.toLocaleString()} min · ${m / 60} h` : `${m.toLocaleString()} min`;
  if (m % 570 === 0 && m >= 570) return `${m.toLocaleString()} min · ${m / 570} business day${m === 570 ? "" : "s"}`;
  if (m % 60 === 0 && m >= 60) return `${m.toLocaleString()} min · ${m / 60} business h`;
  return `${m.toLocaleString()} min`;
}

function vnTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: "Asia/Ho_Chi_Minh",
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function stateTone(state: string): Tone {
  return state === "active" ? "ok" : state === "draft" ? "warn" : "neutral";
}

function refusal(err: unknown): string {
  if (!(err instanceof ApiError)) return "Not done.";
  switch (err.code) {
    case "self_approval":
      return "Another manager approves your draft.";
    case "order_taken":
      return err.message;
    case "default_policy":
      return "The default policy can't be retired.";
    case "invalid_target":
      return "Targets are positive, and the response target is not above the resolution target.";
    default:
      return err.status === 403 ? "You can't do that here." : err.message;
  }
}

const BLANK: PolicyIn = { name: "", order: 50, category: null, priority: "P3", response_minutes: 240, resolution_minutes: 1710, calendar_id: null, is_24x7: false, replaces_id: null };

export default function SlaPoliciesPage() {
  const user = useRequireAuth();
  const [policies, setPolicies] = useState<PolicyOut[] | null>(null);
  const [calendars, setCalendars] = useState<CalendarOut[]>([]);
  const [draft, setDraft] = useState<PolicyIn | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [preview, setPreview] = useState<{ input: PreviewIn & { local: string }; out: PreviewOut | null }>({
    input: { category: "hardware", priority: "P3", start_at: "", local: "2026-10-23T15:30" },
    out: null,
  });

  const load = useCallback(async () => {
    try {
      setPolicies(await api.get<PolicyOut[]>("/api/sla/policies"));
      setCalendars(await api.get<CalendarOut[]>("/api/sla/calendars"));
    } catch {
      setError("Couldn't load the SLA policies.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;
  const isAdmin = (user.capabilities ?? []).includes("workflow_admin");
  const isManager = user.role === "manager";

  const act = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(refusal(err));
    }
  };

  const ask = (verb: string) => window.prompt(`Why ${verb} this policy?`)?.trim();

  const runPreview = async () => {
    const { local, ...rest } = preview.input;
    try {
      const out = await api.post<PreviewOut>("/api/sla/preview", { ...rest, start_at: `${local}:00+07:00` });
      setPreview({ ...preview, out });
    } catch (err) {
      setError(refusal(err));
    }
  };

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">SLA policies</h1>
          <p className="text-xs text-muted-foreground">
            Targets in business minutes on the policy&apos;s calendar. The first active policy by order that matches wins.
          </p>
        </div>
        {isAdmin && (
          <Button onClick={() => setDraft({ ...BLANK })}>
            New policy draft
          </Button>
        )}
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}

      <Card className="overflow-x-auto">
        <Table className="w-full min-w-[980px] text-left text-sm">
          <TableHeader className="bg-background text-[11px] text-muted-foreground">
            <TableRow>
              <TableHead className="px-4 py-2 font-normal">Order</TableHead>
              <TableHead className="px-4 py-2 font-normal">Name</TableHead>
              <TableHead className="px-4 py-2 font-normal">Category</TableHead>
              <TableHead className="px-4 py-2 font-normal">Priority</TableHead>
              <TableHead className="px-4 py-2 font-normal">Response</TableHead>
              <TableHead className="px-4 py-2 font-normal">Resolution</TableHead>
              <TableHead className="px-4 py-2 font-normal">Calendar</TableHead>
              <TableHead className="px-4 py-2 font-normal">State</TableHead>
              <TableHead className="px-4 py-2 font-normal" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {policies?.map((p) => (
              <TableRow key={p.id} className={`border-t border-border ${p.state === "draft" ? "bg-warn-soft" : ""} ${p.state === "retired" ? "text-muted-foreground" : ""}`}>
                <TableCell className="px-4 py-2.5 tabular-nums">{p.order}</TableCell>
                <TableCell className="px-4 py-2.5">{p.name}</TableCell>
                <TableCell className="px-4 py-2.5">{p.category ?? "any"}</TableCell>
                <TableCell className="px-4 py-2.5">{p.priority ? <PriorityChip priority={p.priority} /> : "any"}</TableCell>
                <TableCell className="px-4 py-2.5">{minutesText(p.response_minutes, p.is_24x7)}</TableCell>
                <TableCell className="px-4 py-2.5">{minutesText(p.resolution_minutes, p.is_24x7)}</TableCell>
                <TableCell className="px-4 py-2.5">{p.is_24x7 ? "24×7" : (p.calendar ?? "team's / default")}</TableCell>
                <TableCell className="px-4 py-2.5">
                  <Badge variant={stateTone(p.state)}>
                    {p.state}
                    {p.state === "draft" && p.created_by ? ` · ${p.created_by}` : ""}
                  </Badge>
                </TableCell>
                <TableCell className="whitespace-nowrap px-4 py-2.5 text-right">
                  {p.state === "draft" && isManager && (
                    <Button variant="outline"
                      onClick={() => {
                        const reason = ask("activate");
                        if (reason) void act(() => api.post(`/api/sla/policies/${p.id}/approve`, { reason }));
                      }}
                    >
                      Approve
                    </Button>
                  )}
                  {p.state === "draft" && !isManager && <span className="text-xs text-muted-foreground">Waiting for a manager</span>}
                  {p.state === "active" && isAdmin && (
                    <Button variant="link" size="inline"
                      className="text-xs"
                      onClick={() =>
                        setDraft({
                          name: `${p.name} (new)`,
                          order: p.order,
                          category: p.category as TicketCategory | null,
                          priority: p.priority as Priority | null,
                          response_minutes: p.response_minutes,
                          resolution_minutes: p.resolution_minutes,
                          calendar_id: calendars.find((c) => c.name === p.calendar)?.id ?? null,
                          is_24x7: p.is_24x7,
                          replaces_id: p.id,
                        })
                      }
                    >
                      Draft a change
                    </Button>
                  )}
                  {p.state === "active" && isManager && (
                    <Button variant="link" size="inline"
                      className="ml-3 text-xs text-danger"
                      onClick={() => {
                        const reason = ask("retire");
                        if (reason) void act(() => api.post(`/api/sla/policies/${p.id}/retire`, { reason }));
                      }}
                    >
                      Retire
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Card asChild>
        <section className="flex flex-col gap-3 p-4">
          <h2 className="text-sm font-semibold">Preview due times</h2>
          <div className="flex flex-wrap items-end gap-3 text-sm">
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-muted-foreground">Category</span>
              <NativeSelect
                value={preview.input.category ?? ""}
                onChange={(e) => setPreview({ ...preview, input: { ...preview.input, category: (e.target.value || null) as TicketCategory | null } })}
              >
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-muted-foreground">Priority</span>
              <NativeSelect
                value={preview.input.priority}
                onChange={(e) => setPreview({ ...preview, input: { ...preview.input, priority: e.target.value as Priority } })}
              >
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-muted-foreground">Handoff at (+07)</span>
              <Input
                type="datetime-local"
                value={preview.input.local}
                onChange={(e) => setPreview({ ...preview, input: { ...preview.input, local: e.target.value } })}
              />
            </label>
            <Button variant="outline" onClick={() => void runPreview()}>
              Preview
            </Button>
          </div>
          {preview.out && (
            <div className="flex flex-col gap-1.5">
              <div className="flex flex-wrap gap-2">
                <Badge variant="info">
                  Response due {vnTime(preview.out.response.due_at)} · warn {vnTime(preview.out.response.warn_at)}
                </Badge>
                <Badge variant="info">
                  Resolution due {vnTime(preview.out.resolution.due_at)} · warn {vnTime(preview.out.resolution.warn_at)}
                </Badge>
              </div>
              <p className="text-[11px] text-muted-foreground">
                Policy {preview.out.policy} · {preview.out.calendar}. Weekends and holidays are skipped.
              </p>
            </div>
          )}
        </section>
      </Card>

      <Modal
        open={!!draft}
        onClose={() => setDraft(null)}
        title={draft?.replaces_id ? "Draft a change" : "New policy draft"}
        subtitle="A draft takes effect only when another manager approves it; running clocks keep their targets."
        footer={
          <>
            <Button variant="outline" onClick={() => setDraft(null)}>
              Cancel
            </Button>
            <Button
              disabled={!draft?.name}
              onClick={() => draft && void act(async () => { await api.post("/api/sla/policies", draft); setDraft(null); })}
            >
              Save draft
            </Button>
          </>
        }
      >
        {draft && (
          <div className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
            <label className="flex flex-col gap-1 sm:col-span-2">
              <span className="text-xs text-muted-foreground">Name</span>
              <Input value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Order</span>
              <Input type="number" min={1} value={draft.order} onChange={(e) => setDraft({ ...draft, order: Number(e.target.value) })} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Category</span>
              <NativeSelect value={draft.category ?? ""} onChange={(e) => setDraft({ ...draft, category: (e.target.value || null) as TicketCategory | null })}>
                <option value="">any</option>
                {CATEGORIES.map((c) => (
                  <option key={c} value={c}>
                    {c}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Priority</span>
              <NativeSelect value={draft.priority ?? ""} onChange={(e) => setDraft({ ...draft, priority: (e.target.value || null) as Priority | null })}>
                <option value="">any</option>
                {PRIORITIES.map((p) => (
                  <option key={p} value={p}>
                    {p}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Calendar</span>
              <NativeSelect value={draft.calendar_id ?? ""} onChange={(e) => setDraft({ ...draft, calendar_id: e.target.value || null })}>
                <option value="">team&apos;s, else default</option>
                {calendars.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </NativeSelect>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Response (business minutes)</span>
              <Input type="number" min={1} value={draft.response_minutes} onChange={(e) => setDraft({ ...draft, response_minutes: Number(e.target.value) })} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Resolution (business minutes)</span>
              <Input type="number" min={1} value={draft.resolution_minutes} onChange={(e) => setDraft({ ...draft, resolution_minutes: Number(e.target.value) })} />
            </label>
            <label className="flex items-center gap-2 sm:col-span-2">
              <Checkbox checked={draft.is_24x7 ?? false} onCheckedChange={(checked) => setDraft({ ...draft, is_24x7: checked === true })} />
              Counts around the clock (24×7)
            </label>
          </div>
        )}
      </Modal>
    </div>
  );
}
