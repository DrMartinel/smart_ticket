"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState, TableStatus } from "@/components/ui/states";


// My availability (F2 · My availability 9-603): whether the strategy gives me new tickets, and my leave.

import { useCallback, useEffect, useState } from "react";
import Switch from "@/components/Switch";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { LeaveIn, LeaveOut, MyAvailabilityOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
    <Page width="form" className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Account / Availability"
        title="My availability"
        description={<>Teams: {mine?.memberships.map((m) => `${m.team_name} (${m.role})`).join(", ") || "none"}</>}
      />

      {error && <ErrorState title={error} />}

      <Card asChild>
        <section className="flex items-center justify-between gap-4 p-4">
          <div>
            <p className="text-sm font-medium">Available for new tickets</p>
            <p className="text-xs text-muted-foreground">Off: the team strategy skips you. Tickets you already have stay with you.</p>
          </div>
          <Switch
            checked={available}
            disabled={!mine || mine.memberships.length === 0}
            label="Available for new tickets"
            onChange={(next) => void setAvailable(next)}
          />
        </section>
      </Card>

      <Card asChild>
        <section className="flex flex-col gap-3 p-4">
          <h2 className="text-[11px] font-medium uppercase tracking-wider text-muted-foreground">Leave</h2>
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="py-1.5">From</TableHead>
                <TableHead className="py-1.5">To</TableHead>
                <TableHead className="py-1.5">Note</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {mine?.leaves.map((leave) => (
                <TableRow key={leave.id}>
                  <TableCell className="py-2">{leave.starts_on}</TableCell>
                  <TableCell className="py-2">{leave.ends_on}</TableCell>
                  <TableCell className="py-2">{leave.note || "—"}</TableCell>
                  <TableCell className="py-2 text-right">
                    <Button variant="link" size="inline" className="text-xs" onClick={() => void removeLeave(leave)}>
                      Remove
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
              <TableStatus colSpan={4} rows={mine?.leaves} error={!!error} empty={<EmptyState compact title="No leave booked" />} />
            </TableBody>
          </Table>
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              void addLeave();
            }}
          >
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-foreground/80">From</span>
              <Input type="date" required value={from} onChange={(e) => setFrom(e.target.value)} />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs font-medium text-foreground/80">To</span>
              <Input type="date" value={to} min={from} onChange={(e) => setTo(e.target.value)} />
            </label>
            <label className="flex min-w-[160px] flex-1 flex-col gap-1">
              <span className="text-xs font-medium text-foreground/80">Note</span>
              <Input value={note} maxLength={500} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Annual leave" />
            </label>
            <Button variant="outline" type="submit">
              Add leave
            </Button>
          </form>
        </section>
      </Card>
    </Page>
  );
}
