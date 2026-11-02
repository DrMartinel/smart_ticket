"use client";

// My notification settings (F4 · 11-564): each event that can reach me, per channel, and my language.

import { useEffect, useState } from "react";
import Switch from "@/components/Switch";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { LanguageOut, PreferenceIn, PreferenceOut } from "@/lib/types/generated";
import { NativeSelect } from "@/components/ui/native-select";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const VIA: Record<string, string> = {
  requester: "requester",
  assignee: "assignee",
  previous_assignee: "previous assignee",
  team_lead: "team lead",
  team_members: "team member",
  manager: "manager",
  security: "security",
  workflow_admins: "workflow admin",
  kb_editors: "KB editor",
  incident_managers: "incident manager",
  approver: "approver",
  linked_requesters: "affected requester",
};

interface Row {
  event: string;
  label: string;
  via: string[];
  cells: Partial<Record<"in_app" | "email", PreferenceOut>>;
}

function rows(prefs: PreferenceOut[]): Row[] {
  const byEvent = new Map<string, Row>();
  for (const p of prefs) {
    const row = byEvent.get(p.event) ?? { event: p.event, label: p.label, via: p.via, cells: {} };
    row.cells[p.channel as "in_app" | "email"] = p;
    byEvent.set(p.event, row);
  }
  return [...byEvent.values()];
}

function required(row: Row): string {
  const locked = (["in_app", "email"] as const).filter((c) => row.cells[c]?.mandatory);
  if (locked.length === 0) return "—";
  return `🔒 required${locked.length === 1 ? ` (${locked[0] === "in_app" ? "in-app" : "email"})` : ""}`;
}

export default function MyNotificationsPage() {
  const user = useRequireAuth();
  const [prefs, setPrefs] = useState<PreferenceOut[] | null>(null);
  const [language, setLanguage] = useState<string>("vi");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<string | null>(null);

  useEffect(() => {
    if (!user) return;
    setLanguage(user.language ?? "vi");
    api
      .get<PreferenceOut[]>("/api/notifications/preferences")
      .then(setPrefs)
      .catch(() => setError("Couldn't load your notification settings."));
  }, [user]);

  if (!user) return null;

  const toggle = async (cell: PreferenceOut, enabled: boolean) => {
    const key = `${cell.event}/${cell.channel}`;
    setSaving(key);
    setError(null);
    try {
      const body: PreferenceIn[] = [{ event: cell.event, channel: cell.channel as PreferenceIn["channel"], enabled }];
      setPrefs(await api.put<PreferenceOut[]>("/api/notifications/preferences", body));
    } catch (err) {
      setError(err instanceof ApiError && err.code === "mandatory_cell" ? "That notice is required and can't be turned off." : "Couldn't save that change.");
    } finally {
      setSaving(null);
    }
  };

  const changeLanguage = async (next: string) => {
    setError(null);
    try {
      setLanguage((await api.put<LanguageOut>("/api/notifications/language", { language: next })).language);
    } catch {
      setError("Couldn't change your language.");
    }
  };

  const cell = (row: Row, channel: "in_app" | "email") => {
    const c = row.cells[channel];
    if (!c) return <span className="text-muted-foreground">—</span>;
    return (
      <Switch
        checked={c.enabled}
        disabled={c.mandatory || saving === `${c.event}/${channel}`}
        label={`${row.event} by ${channel === "in_app" ? "in-app" : "email"}`}
        onChange={(next) => void toggle(c, next)}
      />
    );
  };

  return (
    <div className="mx-auto flex max-w-[1100px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">My notification settings</h1>
          <p className="text-xs text-muted-foreground">
            Turn email or in-app off per event. Required notices can&apos;t be turned off.
          </p>
        </div>
        <label className="flex w-[200px] flex-col gap-1">
          <span className="text-[11px] text-muted-foreground">Language of my notices</span>
          <NativeSelect value={language} onChange={(e) => void changeLanguage(e.target.value)}>
            <option value="vi">Tiếng Việt</option>
            <option value="en">English</option>
          </NativeSelect>
        </label>
      </header>

      {error && <p className="text-sm text-danger">{error}</p>}

      <Card className="overflow-x-auto">
        <Table className="w-full min-w-[680px] text-left text-xs">
          <TableHeader className="bg-background text-[11px] text-muted-foreground">
            <TableRow>
              <TableHead className="px-4 py-2 font-normal">Event</TableHead>
              <TableHead className="px-4 py-2 font-normal">When you get it</TableHead>
              <TableHead className="px-4 py-2 font-normal">In-app</TableHead>
              <TableHead className="px-4 py-2 font-normal">Email</TableHead>
              <TableHead className="px-4 py-2 font-normal" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {prefs &&
              rows(prefs).map((row) => (
                <TableRow key={row.event} className="border-t border-border">
                  <TableCell className="px-4 py-2.5">
                    <span className="font-mono">{row.event}</span>
                    <span className="block text-[11px] text-muted-foreground">{row.label}</span>
                  </TableCell>
                  <TableCell className="px-4 py-2.5">As {row.via.map((v) => VIA[v] ?? v).join(", ")}</TableCell>
                  <TableCell className="px-4 py-2.5">{cell(row, "in_app")}</TableCell>
                  <TableCell className="px-4 py-2.5">{cell(row, "email")}</TableCell>
                  <TableCell className="px-4 py-2.5 text-muted-foreground">
                    {required(row)}
                  </TableCell>
                </TableRow>
              ))}
            {prefs?.length === 0 && (
              <TableRow>
                <TableCell colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                  No notices reach you yet.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
      <p className="text-[11px] text-muted-foreground">Changes apply to the next notice and are recorded in the audit log.</p>
    </div>
  );
}
