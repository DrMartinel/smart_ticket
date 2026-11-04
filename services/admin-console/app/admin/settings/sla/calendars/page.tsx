"use client";

// Business calendars (F1 · Business calendars 8-283): working hours per weekday in one zone.

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { CalendarIn, CalendarOut } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";
import { Checkbox } from "@/components/ui/checkbox";
import { SectionTabs } from "@/components/TabNav";

const DAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"] as const;
const LABEL: Record<string, string> = { mon: "Mon", tue: "Tue", wed: "Wed", thu: "Thu", fri: "Fri", sat: "Sat", sun: "Sun" };

function toMinutes(hhmm: string): number {
  const [h, m] = hhmm.split(":").map(Number);
  return h * 60 + m;
}

function spans(hours: CalendarOut["working_hours"], day: string): string {
  const list = hours[day] ?? [];
  return list.length ? list.map(([a, b]) => `${a}–${b}`).join(", ") : "";
}

function dayMinutes(hours: CalendarOut["working_hours"], day: string): number {
  return (hours[day] ?? []).reduce((sum, [a, b]) => sum + toMinutes(b) - toMinutes(a), 0);
}

function parseDay(text: string): string[][] {
  return text
    .split(",")
    .map((s) => s.trim())
    .filter(Boolean)
    .map((s) => s.split(/[–-]/).map((t) => t.trim()));
}

export default function CalendarsPage() {
  const user = useRequireAuth();
  const [calendars, setCalendars] = useState<CalendarOut[] | null>(null);
  const [editing, setEditing] = useState<{ id: string | null; form: CalendarIn; text: Record<string, string> } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setCalendars(await api.get<CalendarOut[]>("/api/sla/calendars"));
    } catch {
      setError("Couldn't load the calendars.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;
  const isAdmin = (user.capabilities ?? []).includes("workflow_admin");

  const open = (calendar: CalendarOut | null) => {
    setError(null);
    const form: CalendarIn = calendar
      ? { name: calendar.name, timezone: calendar.timezone, working_hours: calendar.working_hours, is_default: calendar.is_default }
      : { name: "", timezone: "Asia/Ho_Chi_Minh", working_hours: {}, is_default: false };
    setEditing({ id: calendar?.id ?? null, form, text: Object.fromEntries(DAYS.map((d) => [d, spans(form.working_hours, d)])) });
  };

  const save = async () => {
    if (!editing) return;
    const body = { ...editing.form, working_hours: Object.fromEntries(DAYS.map((d) => [d, parseDay(editing.text[d] ?? "")])) };
    try {
      if (editing.id) await api.patch(`/api/sla/calendars/${editing.id}`, body);
      else await api.post("/api/sla/calendars", body);
      setEditing(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't save the calendar.");
    }
  };

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <SectionTabs className="mb-1" />
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Business calendars</h1>
          <p className="text-xs text-muted-foreground">
            Working time for SLA clocks. A clock uses its policy&apos;s calendar (24×7 overrides), else its team&apos;s, else the default.
          </p>
        </div>
        {isAdmin && (
          <Button onClick={() => open(null)}>
            New calendar
          </Button>
        )}
      </header>

      {error && !editing && <p className="text-sm text-danger">{error}</p>}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {calendars?.map((c) => (
          <Card asChild key={c.id}>
            <section className="flex flex-col gap-3 p-4">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="font-medium">{c.name}</h2>
                {c.is_default && <Badge variant="info">default</Badge>}
                <Badge variant="neutral">{c.timezone}</Badge>
              </div>
              <Table className="w-full text-left text-sm">
                <TableHeader className="text-[11px] text-muted-foreground">
                  <TableRow>
                    <TableHead className="py-1.5 font-normal">Day</TableHead>
                    <TableHead className="py-1.5 font-normal">Working hours</TableHead>
                    <TableHead className="py-1.5 text-right font-normal">Minutes</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {DAYS.map((d) => (
                    <TableRow key={d} className="border-t border-border">
                      <TableCell className="py-1.5">{LABEL[d]}</TableCell>
                      <TableCell className="py-1.5">{spans(c.working_hours, d) || <span className="text-muted-foreground">Closed</span>}</TableCell>
                      <TableCell className="py-1.5 text-right tabular-nums">{dayMinutes(c.working_hours, d)}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              <div className="flex gap-2">
                {isAdmin && (
                  <Button variant="outline" onClick={() => open(c)}>
                    Edit hours
                  </Button>
                )}
                <Button asChild variant="outline">
                  <Link href={`/admin/settings/sla/holidays?calendar=${c.id}`}>Holidays ({c.holidays_count})</Link>
                </Button>
              </div>
            </section>
          </Card>
        ))}
      </div>

      <Modal
        open={!!editing}
        onClose={() => setEditing(null)}
        title={editing?.id ? `Edit ${editing.form.name}` : "New calendar"}
        subtitle="Hours as 08:00–17:30; several intervals separated by commas; empty means closed. Changes reach running clocks at their next recompute."
        footer={
          <>
            <Button variant="outline" onClick={() => setEditing(null)}>
              Cancel
            </Button>
            <Button onClick={() => void save()}>
              Save
            </Button>
          </>
        }
      >
        {editing && (
          <div className="flex flex-col gap-3 text-sm">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Name</span>
                <Input value={editing.form.name} onChange={(e) => setEditing({ ...editing, form: { ...editing.form, name: e.target.value } })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Time zone (IANA)</span>
                <Input className="font-mono" value={editing.form.timezone} onChange={(e) => setEditing({ ...editing, form: { ...editing.form, timezone: e.target.value } })} />
              </label>
            </div>
            {DAYS.map((d) => (
              <label key={d} className="grid grid-cols-[48px_1fr] items-center gap-2">
                <span>{LABEL[d]}</span>
                <Input className="font-mono" value={editing.text[d] ?? ""} placeholder="closed" onChange={(e) => setEditing({ ...editing, text: { ...editing.text, [d]: e.target.value } })} />
              </label>
            ))}
            <label className="flex items-center gap-2">
              <Checkbox checked={editing.form.is_default ?? false} onCheckedChange={(checked) => setEditing({ ...editing, form: { ...editing.form, is_default: checked === true } })} />
              Default calendar
            </label>
            {error && <p className="rounded-md bg-danger-soft px-3 py-2 text-danger">{error}</p>}
          </div>
        )}
      </Modal>
    </div>
  );
}
