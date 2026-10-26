"use client";

// The notification matrix (F4 · 11-710): who gets each event on which channel by default.

import { useEffect, useMemo, useState } from "react";
import Switch from "@/components/Switch";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { MatrixCellOut, MatrixChangeIn, MatrixIn, RecipientKind } from "@/lib/types/generated";

type Channel = "in_app" | "email";

interface Row {
  key: string;
  event: string;
  label: string;
  owner: string;
  active: boolean;
  kind: RecipientKind;
  cells: Partial<Record<Channel, MatrixCellOut>>;
}

const cellKey = (event: string, kind: string, channel: string) => `${event}|${kind}|${channel}`;

function rows(cells: MatrixCellOut[]): Row[] {
  const byRow = new Map<string, Row>();
  for (const c of cells) {
    const key = `${c.event}|${c.recipient_kind}`;
    const row = byRow.get(key) ?? {
      key,
      event: c.event,
      label: c.label,
      owner: c.owner,
      active: c.active,
      kind: c.recipient_kind as RecipientKind,
      cells: {},
    };
    row.cells[c.channel as Channel] = c;
    byRow.set(key, row);
  }
  return [...byRow.values()];
}

function refusal(err: unknown): string {
  if (!(err instanceof ApiError)) return "Couldn't save the matrix.";
  switch (err.code) {
    case "reason_required":
      return "Say why the defaults change.";
    case "mandatory_cell":
      return "A mandatory notice can't be turned off.";
    case "unknown_event":
      return "That event isn't in the catalog.";
    default:
      return err.status === 403 ? "Only a workflow admin can change the matrix." : err.message;
  }
}

export default function NotificationMatrixPage() {
  const user = useRequireAuth();
  const [cells, setCells] = useState<MatrixCellOut[] | null>(null);
  const [pending, setPending] = useState<Record<string, boolean>>({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [showInactive, setShowInactive] = useState(false);
  const canEdit = user?.capabilities?.includes("workflow_admin") ?? false;

  useEffect(() => {
    if (!user) return;
    api
      .get<MatrixCellOut[]>("/api/notifications/matrix")
      .then(setCells)
      .catch((err) => setError(err instanceof ApiError && err.status === 403 ? "Only managers and workflow admins can see the matrix." : "Couldn't load the matrix."));
  }, [user]);

  const all = useMemo(() => (cells ? rows(cells) : []), [cells]);
  const shown = all.filter((r) => r.active || showInactive);
  const inactive = all.filter((r) => !r.active).length;
  const changes = Object.keys(pending).length;

  if (!user) return null;

  const valueOf = (c: MatrixCellOut) => pending[cellKey(c.event, c.recipient_kind, c.channel)] ?? c.default_on;

  const flip = (c: MatrixCellOut, next: boolean) => {
    setSaved(false);
    const key = cellKey(c.event, c.recipient_kind, c.channel);
    setPending((p) => {
      const copy = { ...p };
      if (next === c.default_on) delete copy[key];
      else copy[key] = next;
      return copy;
    });
  };

  const save = async () => {
    setError(null);
    const body: MatrixIn = {
      reason,
      changes: Object.entries(pending).map(([key, default_on]): MatrixChangeIn => {
        const [event, recipient_kind, channel] = key.split("|");
        return { event, recipient_kind: recipient_kind as RecipientKind, channel: channel as Channel, default_on };
      }),
    };
    try {
      setCells(await api.put<MatrixCellOut[]>("/api/notifications/matrix", body));
      setPending({});
      setReason("");
      setSaved(true);
    } catch (err) {
      setError(refusal(err));
    }
  };

  const cell = (row: Row, channel: Channel) => {
    const c = row.cells[channel];
    if (!c) return <span className="text-[var(--text-muted)]">—</span>;
    return (
      <Switch
        checked={valueOf(c)}
        disabled={!canEdit || c.mandatory}
        label={`${row.event} to ${row.kind} by ${channel === "in_app" ? "in-app" : "email"}`}
        onChange={(next) => flip(c, next)}
      />
    );
  };

  return (
    <div className="mx-auto flex max-w-[1280px] flex-col gap-4">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Notification matrix</h1>
          <p className="text-xs text-[var(--text-muted)]">
            Defaults for who gets each event on which channel. Events and recipient kinds are code; defaults are data.
          </p>
        </div>
        {canEdit && (
          <button className="btn btn-primary" disabled={changes === 0} onClick={() => void save()}>
            Save {changes > 0 ? `${changes} change${changes > 1 ? "s" : ""}` : "changes"}…
          </button>
        )}
      </header>

      {!canEdit && cells && <p className="text-xs text-[var(--text-muted)]">Read-only: only a workflow admin changes defaults.</p>}
      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
      {saved && <p className="text-sm text-[var(--ok)]">Saved. The change is in the audit log.</p>}

      <div className="card overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-xs">
          <thead className="bg-[var(--bg)] text-[11px] text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2 font-normal">Event</th>
              <th className="px-4 py-2 font-normal">Recipient</th>
              <th className="px-4 py-2 font-normal">In-app</th>
              <th className="px-4 py-2 font-normal">Email</th>
              <th className="px-4 py-2 font-normal">Mandatory</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((row) => (
              <tr key={row.key} className={`border-t border-[var(--border)] ${row.active ? "" : "text-[var(--text-muted)]"}`}>
                <td className="px-4 py-2.5">
                  <span className="font-mono">{row.event}</span>
                  {!row.active && <span className="ml-2 badge tone-neutral">ships with {row.owner}</span>}
                </td>
                <td className="px-4 py-2.5">{row.kind.replaceAll("_", " ")}</td>
                <td className="px-4 py-2.5">{cell(row, "in_app")}</td>
                <td className="px-4 py-2.5">{cell(row, "email")}</td>
                <td className="px-4 py-2.5 text-[var(--text-muted)]">
                  {(["in_app", "email"] as const).filter((c) => row.cells[c]?.mandatory).length === 2
                    ? "🔒 mandatory"
                    : row.cells.in_app?.mandatory
                      ? "🔒 in-app"
                      : row.cells.email?.mandatory
                        ? "🔒 email"
                        : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {inactive > 0 && (
        <button className="self-start text-xs text-[var(--accent)] hover:underline" onClick={() => setShowInactive((s) => !s)}>
          {showInactive ? "Hide" : "Show"} {inactive} rows for events of features not built yet
        </button>
      )}

      {canEdit && (
        <div className="card flex flex-col gap-2 p-4">
          <label className="flex flex-col gap-1">
            <span className="text-[11px] text-[var(--text-muted)]">Reason (required when saving)</span>
            <input value={reason} onChange={(e) => setReason(e.target.value)} maxLength={500} className="field max-w-[640px]" placeholder="Why the defaults change" />
          </label>
          <p className="text-[11px] text-[var(--text-muted)]">Saving writes notif_matrix_changed to the audit log. Mandatory cells are read-only.</p>
        </div>
      )}
    </div>
  );
}
