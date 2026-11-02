"use client";

// My availability (F2 · My availability 9-603): whether the strategy gives me new tickets, and my leave.

import { useCallback, useEffect, useState } from "react";
import Switch from "@/components/Switch";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { LeaveIn, LeaveOut, MyAvailabilityOut } from "@/lib/types/generated";

export default function MyAvailabilityPage() {
  const user = useRequireAuth();
  const [mine, setMine] = useState<MyAvailabilityOut | null>(null);
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setMine(await api.get<MyAvailabilityOut>("/api/me/availability"));
    } catch {
      setError("Couldn't load your availability.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;

  const available = mine ? mine.memberships.length > 0 && mine.memberships.every((m) => m.is_available) : false;

  const setAvailable = async (next: boolean) => {
    setError(null);
    try {
      setMine(await api.put<MyAvailabilityOut>("/api/me/availability", { is_available: next }));
    } catch {
      setError("Couldn't change your availability.");
    }
  };

  const addLeave = async () => {
    setError(null);
    const body: LeaveIn = { starts_on: from, ends_on: to || from, note };
    try {
      await api.post<LeaveOut>("/api/me/leaves", body);
      setFrom("");
      setTo("");
      setNote("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError && err.code === "bad_dates" ? "The leave ends before it starts." : "Couldn't add the leave.");
    }
  };

  const removeLeave = async (leave: LeaveOut) => {
    setError(null);
    try {
      await api.delete<void>(`/api/me/leaves/${leave.id}`);
      await load();
    } catch {
      setError("Couldn't remove the leave.");
    }
  };

  return (
    <div className="mx-auto flex max-w-[640px] flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold">My availability</h1>
        <p className="text-xs text-[var(--text-muted)]">
          Teams: {mine?.memberships.map((m) => `${m.team_name} (${m.role})`).join(", ") || "none"}
        </p>
      </header>

      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}

      <section className="card flex items-center justify-between gap-4 p-4">
        <div>
          <p className="text-sm font-medium">Available for new tickets</p>
          <p className="text-xs text-[var(--text-muted)]">Off: the team strategy skips you. Tickets you already have stay with you.</p>
        </div>
        <Switch
          checked={available}
          disabled={!mine || mine.memberships.length === 0}
          label="Available for new tickets"
          onChange={(next) => void setAvailable(next)}
        />
      </section>

      <section className="card flex flex-col gap-3 p-4">
        <h2 className="text-[11px] font-medium uppercase tracking-wider text-[var(--text-muted)]">Leave</h2>
        <table className="w-full text-left text-sm">
          <thead className="text-[11px] text-[var(--text-muted)]">
            <tr>
              <th className="py-1.5 font-normal">From</th>
              <th className="py-1.5 font-normal">To</th>
              <th className="py-1.5 font-normal">Note</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {mine?.leaves.map((leave) => (
              <tr key={leave.id} className="border-t border-[var(--border)]">
                <td className="py-2">{leave.starts_on}</td>
                <td className="py-2">{leave.ends_on}</td>
                <td className="py-2">{leave.note || "—"}</td>
                <td className="py-2 text-right">
                  <button className="text-xs text-[var(--accent)] hover:underline" onClick={() => void removeLeave(leave)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {mine?.leaves.length === 0 && (
              <tr>
                <td colSpan={4} className="py-3 text-[var(--text-muted)]">
                  No leave booked.
                </td>
              </tr>
            )}
          </tbody>
        </table>
        <form
          className="flex flex-wrap items-end gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            void addLeave();
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-[var(--text-muted)]">From</span>
            <input type="date" required className="field" value={from} onChange={(e) => setFrom(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-[var(--text-muted)]">To</span>
            <input type="date" className="field" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
          </label>
          <label className="flex min-w-[160px] flex-1 flex-col gap-1">
            <span className="text-[11px] text-[var(--text-muted)]">Note</span>
            <input className="field" value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="Nghỉ phép" />
          </label>
          <button type="submit" className="btn btn-secondary">
            Add leave
          </button>
        </form>
      </section>
    </div>
  );
}
