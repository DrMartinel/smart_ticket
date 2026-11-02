"use client";

// Holidays (F1 · Holidays 8-435): whole days off per calendar, entered each year.

import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { CalendarOut, HolidayOut } from "@/lib/types/generated";
import { NativeSelect } from "@/components/ui/native-select";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Run {
  first: HolidayOut;
  last: HolidayOut;
  ids: string[];
}

function weekday(date: string): string {
  return new Date(`${date}T00:00:00Z`).toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
}

/** Consecutive days with the same name, shown as one row (Tết). */
function runs(holidays: HolidayOut[]): Run[] {
  const out: Run[] = [];
  for (const h of holidays) {
    const prev = out[out.length - 1];
    const next = prev && new Date(`${prev.last.date}T00:00:00Z`).getTime() + 86_400_000 === new Date(`${h.date}T00:00:00Z`).getTime();
    if (prev && next && prev.first.name === h.name) {
      prev.last = h;
      prev.ids.push(h.id);
    } else out.push({ first: h, last: h, ids: [h.id] });
  }
  return out;
}

export default function HolidaysPage() {
  const user = useRequireAuth();
  const search = useSearchParams();
  const [calendars, setCalendars] = useState<CalendarOut[]>([]);
  const [calendarId, setCalendarId] = useState(search.get("calendar") ?? "");
  const [holidays, setHolidays] = useState<HolidayOut[]>([]);
  const [year, setYear] = useState(String(new Date().getFullYear() + 1));
  const [form, setForm] = useState({ from: "", to: "", name: "" });
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    api
      .get<CalendarOut[]>("/api/sla/calendars")
      .then((list) => {
        setCalendars(list);
        setCalendarId((current) => current || list.find((c) => c.is_default)?.id || list[0]?.id || "");
      })
      .catch(() => setError("Couldn't load the calendars."));
  }, [user]);

  const load = useCallback(async () => {
    if (!calendarId) return;
    try {
      setHolidays(await api.get<HolidayOut[]>(`/api/sla/calendars/${calendarId}/holidays`));
    } catch {
      setError("Couldn't load the holidays.");
    }
  }, [calendarId]);

  useEffect(() => {
    void load();
  }, [load]);

  const years = useMemo(() => [...new Set(holidays.map((h) => h.date.slice(0, 4)).concat(year))].sort(), [holidays, year]);
  const shown = runs(holidays.filter((h) => h.date.startsWith(year)));

  if (!user) return null;
  const isAdmin = (user.capabilities ?? []).includes("workflow_admin");
  const calendar = calendars.find((c) => c.id === calendarId);
  const nextYear = String(Number(year) + 1);
  const nextHas = holidays.some((h) => h.date.startsWith(nextYear));

  const add = async () => {
    setError(null);
    try {
      await api.post(`/api/sla/calendars/${calendarId}/holidays`, { from: form.from, to: form.to || form.from, name: form.name });
      setForm({ from: "", to: "", name: "" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't add the holiday.");
    }
  };

  const remove = async (run: Run) => {
    setError(null);
    try {
      for (const id of run.ids) await api.delete(`/api/sla/calendars/${calendarId}/holidays/${id}`);
      await load();
    } catch {
      setError("Couldn't remove the holiday.");
    }
  };

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Holidays{calendar ? ` — ${calendar.name}` : ""}</h1>
          <p className="text-xs text-muted-foreground">Whole days in {calendar?.timezone ?? "the calendar's zone"}. HR confirms the dates each year.</p>
        </div>
        <div className="flex flex-wrap items-end gap-3">
          <label className="flex w-[180px] flex-col gap-1">
            <span className="text-[11px] text-muted-foreground">Calendar</span>
            <NativeSelect value={calendarId} onChange={(e) => setCalendarId(e.target.value)}>
              {calendars.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </NativeSelect>
          </label>
          <label className="flex w-[110px] flex-col gap-1">
            <span className="text-[11px] text-muted-foreground">Year</span>
            <NativeSelect value={year} onChange={(e) => setYear(e.target.value)}>
              {years.map((y) => (
                <option key={y} value={y}>
                  {y}
                </option>
              ))}
            </NativeSelect>
          </label>
        </div>
      </header>

      <p className="rounded-md bg-info-soft px-3 py-2 text-sm text-info">
        {year}: {holidays.filter((h) => h.date.startsWith(year)).length} days entered.
        {!nextHas && ` ${nextYear} has none yet; from 1 Dec ${year} workflow admins get a reminder.`} Edits reach running clocks at their next
        recompute.
      </p>
      {error && <p className="text-sm text-danger">{error}</p>}

      <Card className="overflow-x-auto">
        <Table className="w-full min-w-[640px] text-left text-sm">
          <TableHeader className="bg-background text-[11px] text-muted-foreground">
            <TableRow>
              <TableHead className="px-4 py-2 font-normal">Date</TableHead>
              <TableHead className="px-4 py-2 font-normal">Weekday</TableHead>
              <TableHead className="px-4 py-2 font-normal">Name</TableHead>
              <TableHead className="px-4 py-2 font-normal">Days</TableHead>
              <TableHead className="px-4 py-2 font-normal" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {shown.map((run) => (
              <TableRow key={run.first.id} className="border-t border-border">
                <TableCell className="whitespace-nowrap px-4 py-2.5">
                  {run.first.date}
                  {run.ids.length > 1 && ` → ${run.last.date}`}
                </TableCell>
                <TableCell className="px-4 py-2.5">
                  {weekday(run.first.date)}
                  {run.ids.length > 1 && ` → ${weekday(run.last.date)}`}
                </TableCell>
                <TableCell className="px-4 py-2.5">{run.first.name}</TableCell>
                <TableCell className="px-4 py-2.5 tabular-nums">{run.ids.length}</TableCell>
                <TableCell className="px-4 py-2.5 text-right">
                  {isAdmin && (
                    <Button variant="link" size="inline" className="text-xs" onClick={() => void remove(run)}>
                      Remove
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {shown.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                  No holidays entered for {year}.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>

      {isAdmin && (
        <Card asChild>
          <form
            className="flex flex-wrap items-end gap-3 p-4"
            onSubmit={(e) => {
              e.preventDefault();
              void add();
            }}
          >
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-muted-foreground">From</span>
              <Input type="date" required value={form.from} onChange={(e) => setForm({ ...form, from: e.target.value })} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-[11px] text-muted-foreground">To (for a range like Tết)</span>
              <Input type="date" min={form.from} value={form.to} onChange={(e) => setForm({ ...form, to: e.target.value })} />
            </label>
            <label className="flex min-w-[200px] flex-1 flex-col gap-1">
              <span className="text-[11px] text-muted-foreground">Name</span>
              <Input required value={form.name} maxLength={100} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="Tết Nguyên đán" />
            </label>
            <Button type="submit">
              Add holiday
            </Button>
          </form>
        </Card>
      )}
    </div>
  );
}
