"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState, TableStatus } from "@/components/ui/states";

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
    <Page className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Account / Notifications"
        title="My notification settings"
        description={<>Turn email or in-app off per event. Required notices can&apos;t be turned off.</>}
        actions={
      <>
      <label className="flex w-[200px] flex-col gap-1">
        <span className="text-xs font-medium text-foreground/80">Language of my notices</span>
        <NativeSelect value={language} onChange={(e) => void changeLanguage(e.target.value)}>
          <option value="vi">Tiếng Việt</option>
          <option value="en">English</option>
        </NativeSelect>
      </label>
      </>
      }
      />

      {error && <ErrorState title={error} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[680px] text-xs">
          <TableHeader>
            <TableRow>
              <TableHead>Event</TableHead>
              <TableHead>When you get it</TableHead>
              <TableHead>In-app</TableHead>
              <TableHead>Email</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {prefs &&
              rows(prefs).map((row) => (
                <TableRow key={row.event}>
                  <TableCell>
                    <span className="font-mono">{row.event}</span>
                    <span className="block text-[11px] text-muted-foreground">{row.label}</span>
                  </TableCell>
                  <TableCell>As {row.via.map((v) => VIA[v] ?? v).join(", ")}</TableCell>
                  <TableCell>{cell(row, "in_app")}</TableCell>
                  <TableCell>{cell(row, "email")}</TableCell>
                  <TableCell className="text-muted-foreground">
                    {required(row)}
                  </TableCell>
                </TableRow>
              ))}
            <TableStatus colSpan={5} rows={prefs} error={!!error} empty={<EmptyState compact title="No notices reach you yet" />} />
          </TableBody>
        </Table>
      </Card>
      <p className="text-xs text-muted-foreground">Changes apply to the next notice and are recorded in the audit log.</p>
    </Page>
  );
}
