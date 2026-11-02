"use client";

// Business calendars (F1 · Business calendars 8-283): working hours per weekday in one zone.

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import Modal from "@/components/Modal";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { CalendarIn, CalendarOut } from "@/lib/types/generated";

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
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Business calendars</h1>
          <p className="text-xs text-[var(--text-muted)]">
            Working time for SLA clocks. A clock uses its policy&apos;s calendar (24×7 overrides), else its team&apos;s, else the default.
          </p>
        </div>
        {isAdmin && (
          <button className="btn btn-primary" onClick={() => open(null)}>
            New calendar
          </button>
        )}
      </header>

      {error && !editing && <p className="text-sm text-[var(--danger)]">{error}</p>}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {calendars?.map((c) => (
          <section key={c.id} className="card flex flex-col gap-3 p-4">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="font-medium">{c.name}</h2>
              {c.is_default && <span className="badge tone-info">default</span>}
              <span className="badge tone-neutral">{c.timezone}</span>
            </div>
            <table className="w-full text-left text-sm">
              <thead className="text-[11px] text-[var(--text-muted)]">
                <tr>
                  <th className="py-1.5 font-normal">Day</th>
                  <th className="py-1.5 font-normal">Working hours</th>
                  <th className="py-1.5 text-right font-normal">Minutes</th>
                </tr>
              </thead>
              <tbody>
                {DAYS.map((d) => (
                  <tr key={d} className="border-t border-[var(--border)]">
                    <td className="py-1.5">{LABEL[d]}</td>
                    <td className="py-1.5">{spans(c.working_hours, d) || <span className="text-[var(--text-muted)]">Closed</span>}</td>
                    <td className="py-1.5 text-right tabular-nums">{dayMinutes(c.working_hours, d)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div className="flex gap-2">
              {isAdmin && (
                <button className="btn btn-secondary" onClick={() => open(c)}>
                  Edit hours
                </button>
              )}
              <Link className="btn btn-secondary" href={`/settings/sla/holidays?calendar=${c.id}`}>
                Holidays ({c.holidays_count})
              </Link>
            </div>
          </section>
        ))}
      </div>

      <Modal
        open={!!editing}
        onClose={() => setEditing(null)}
        title={editing?.id ? `Edit ${editing.form.name}` : "New calendar"}
        subtitle="Hours as 08:00–17:30; several intervals separated by commas; empty means closed. Changes reach running clocks at their next recompute."
        footer={
          <>
            <button className="btn btn-secondary" onClick={() => setEditing(null)}>
              Cancel
            </button>
            <button className="btn btn-primary" onClick={() => void save()}>
              Save
            </button>
          </>
        }
      >
        {editing && (
          <div className="flex flex-col gap-3 text-sm">
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <label className="flex flex-col gap-1">
                <span className="text-xs text-[var(--text-muted)]">Name</span>
                <input className="field" value={editing.form.name} onChange={(e) => setEditing({ ...editing, form: { ...editing.form, name: e.target.value } })} />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-[var(--text-muted)]">Time zone (IANA)</span>
                <input className="field font-mono" value={editing.form.timezone} onChange={(e) => setEditing({ ...editing, form: { ...editing.form, timezone: e.target.value } })} />
              </label>
            </div>
            {DAYS.map((d) => (
              <label key={d} className="grid grid-cols-[48px_1fr] items-center gap-2">
                <span>{LABEL[d]}</span>
                <input className="field font-mono" value={editing.text[d] ?? ""} placeholder="closed" onChange={(e) => setEditing({ ...editing, text: { ...editing.text, [d]: e.target.value } })} />
              </label>
            ))}
            <label className="flex items-center gap-2">
              <input type="checkbox" checked={editing.form.is_default ?? false} onChange={(e) => setEditing({ ...editing, form: { ...editing.form, is_default: e.target.checked } })} />
              Default calendar
            </label>
            {error && <p className="rounded-[5px] bg-[var(--danger-soft)] px-3 py-2 text-[var(--danger)]">{error}</p>}
          </div>
        )}
      </Modal>
    </div>
  );
}
