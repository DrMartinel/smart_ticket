"use client";

import { useEffect, useState } from "react";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import Modal, { Labeled } from "@/components/Modal";
import StatusChip from "@/components/StatusChip";
import { ColorPicker } from "@/components/workflow/Dialogs";
import { PALETTE, type Stage } from "@/lib/lifecycle";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";

type Kind = "backlog" | "active" | "completed";

const KIND_LABEL: Record<Kind, string> = {
  backlog: "Not started",
  active: "In progress",
  completed: "Resolved",
};

const kindOf = (s: Stage): Kind => (s.is_completed ? "completed" : s.is_backlog ? "backlog" : "active");

export default function StagesPage() {
  const user = useRequireAuth();
  const [stages, setStages] = useState<Stage[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<Stage | "new" | null>(null);

  const load = () =>
    api
      .get<Stage[]>("/api/lifecycle/system-statuses")
      .then((s) => setStages([...s].sort((a, b) => a.order - b.order)))
      .catch(() => setError("Couldn't load stages."));

  useEffect(() => {
    if (user) void load();
  }, [user]);

  if (!user) return null;
  const canEdit = user.role === "manager";

  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work.");
    }
  };

  const move = (i: number, d: number) => {
    if (!stages) return;
    const next = [...stages];
    [next[i], next[i + d]] = [next[i + d], next[i]];
    setStages(next);
    void run(() => api.post("/api/lifecycle/system-statuses/reorder", { ids: next.map((s) => s.id) }));
  };

  return (
    <div className="mx-auto max-w-[880px]">
      <header className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Stages</h1>
          <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">
            The system stages every workflow status maps onto. Reports and SLAs read the stage, so workflows can name their statuses freely.
          </p>
        </div>
        {canEdit && (
          <Button onClick={() => setEditing("new")}>
            New stage
          </Button>
        )}
      </header>

      {error && <Alert variant="danger" className="mb-4 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}

      {stages && (
        <Card className="overflow-hidden">
          <Table className="w-full text-sm">
            <TableHeader className="bg-muted text-left text-xs text-muted-foreground">
              <TableRow>
                <TableHead className="w-12 px-4 py-2.5 font-medium">#</TableHead>
                <TableHead className="px-4 py-2.5 font-medium">Stage</TableHead>
                <TableHead className="px-4 py-2.5 font-medium">Counts as</TableHead>
                <TableHead className="px-4 py-2.5" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {stages.map((s, i) => (
                <TableRow key={s.id} className="border-t border-border">
                  <TableCell className="px-4 py-3 text-muted-foreground">{i + 1}</TableCell>
                  <TableCell className="px-4 py-3">
                    <StatusChip name={s.name} color={s.color} />
                    {s.description && <p className="text-xs text-muted-foreground">{s.description}</p>}
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    <Badge variant={s.is_completed ? "ok" : s.is_backlog ? "neutral" : "info"}>{KIND_LABEL[kindOf(s)]}</Badge>
                  </TableCell>
                  <TableCell className="px-4 py-3">
                    {canEdit && (
                      <span className="flex items-center justify-end gap-1 text-xs">
                        <Button variant="outline" size="sm" disabled={i === 0} onClick={() => move(i, -1)} aria-label={`Move ${s.name} up`}>
                          ↑
                        </Button>
                        <Button variant="outline" size="sm"
                          disabled={i === stages.length - 1}
                          onClick={() => move(i, 1)}
                          aria-label={`Move ${s.name} down`}
                        >
                          ↓
                        </Button>
                        <Button variant="link" size="inline" className="ml-2" onClick={() => setEditing(s)}>
                          Edit
                        </Button>
                        <Button variant="link" size="inline"
                          className="ml-2 text-danger"
                          onClick={() => confirm(`Delete stage "${s.name}"?`) && run(() => api.delete(`/api/lifecycle/system-statuses/${s.id}`))}
                        >
                          Delete
                        </Button>
                      </span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      <StageDialog
        stage={editing === "new" ? null : editing}
        open={editing !== null}
        onClose={() => setEditing(null)}
        onSave={async (body) => {
          if (editing === "new") await api.post("/api/lifecycle/system-statuses", body);
          else if (editing) await api.patch(`/api/lifecycle/system-statuses/${editing.id}`, body);
          setEditing(null);
          await load();
        }}
      />
    </div>
  );
}

function StageDialog({
  stage,
  open,
  onClose,
  onSave,
}: {
  stage: Stage | null;
  open: boolean;
  onClose: () => void;
  onSave: (body: object) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [color, setColor] = useState(PALETTE[0]);
  const [kind, setKind] = useState<Kind>("active");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open) return;
    setError(null);
    setName(stage?.name ?? "");
    setDescription(stage?.description ?? "");
    setColor(stage?.color ?? PALETTE[0]);
    setKind(stage ? kindOf(stage) : "active");
  }, [open, stage]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave({ name: name.trim(), description, color, is_backlog: kind === "backlog", is_completed: kind === "completed" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={stage ? `Edit ${stage.name}` : "New stage"}
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={busy || !name.trim()} onClick={save}>
            Save
          </Button>
        </>
      }
    >
      {error && <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}
      <div className="grid gap-4">
        <Labeled label="Name">
          <Input value={name} onChange={(e) => setName(e.target.value)} autoFocus />
        </Labeled>
        <Labeled label="Description">
          <Input value={description} onChange={(e) => setDescription(e.target.value)} />
        </Labeled>
        <ColorPicker value={color} onChange={setColor} />
        <fieldset className="text-sm">
          <legend className="mb-2 text-xs font-medium text-muted-foreground">Counts as</legend>
          <RadioGroup value={kind} onValueChange={(next) => setKind(next as Kind)} className="gap-2">
          {(["backlog", "active", "completed"] as Kind[]).map((k) => (
            <label key={k} className="flex items-center gap-2">
              <RadioGroupItem value={k} />
              {KIND_LABEL[k]}
              <span className="text-xs text-muted-foreground">
                {k === "completed" ? "the ticket is resolved and its SLA stops" : k === "backlog" ? "not yet picked up" : "someone is working on it"}
              </span>
            </label>
          ))}
          </RadioGroup>
        </fieldset>
      </div>
    </Modal>
  );
}
