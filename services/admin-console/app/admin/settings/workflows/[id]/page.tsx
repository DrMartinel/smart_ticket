"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { ErrorState, LoadingState } from "@/components/ui/states";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { humanize } from "@/lib/format";
import StatusChip from "@/components/StatusChip";
import { Tabs } from "@/components/Modal";
import WorkflowCanvas from "@/components/workflow/WorkflowCanvas";
import FieldDialog from "@/components/workflow/FieldDialog";
import { DeleteDialog, ReorderDialog, StatusDialog, TransitionDialog, type TransitionDraft } from "@/components/workflow/Dialogs";
import { KIND_LABEL, type Action, type Catalog, type Field, type Status, type Transition, type Workflow, type WorkflowDetail } from "@/lib/lifecycle";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { P, can } from "@/lib/permissions";

type Selection = { kind: "status" | "transition"; id: string } | null;
type Open =
  | { kind: "status"; status: Status | null }
  | { kind: "transition"; transition: Transition | null; draft?: TransitionDraft }
  | { kind: "reorder" }
  | { kind: "field"; field: Field | null }
  | { kind: "delete"; status?: Status; transition?: Transition }
  | null;

export default function WorkflowEditorPage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const [wf, setWf] = useState<WorkflowDetail | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [workflows, setWorkflows] = useState<Workflow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<"diagram" | "fields">("diagram");
  const [selected, setSelected] = useState<Selection>(null);
  const [open, setOpen] = useState<Open>(null);

  const load = useCallback(async () => {
    try {
      const [w, c, all] = await Promise.all([
        api.get<WorkflowDetail>(`/api/lifecycle/workflows/${id}`),
        api.get<Catalog>("/api/lifecycle/catalog"),
        api.get<Workflow[]>("/api/lifecycle/workflows"),
      ]);
      setWf(w);
      setCatalog(c);
      setWorkflows(all);
    } catch {
      setError("Couldn't load this workflow.");
    }
  }, [id]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  const context = useMemo(
    () => ({ fields: wf?.fields ?? [], statuses: wf?.statuses ?? [], workflows: workflows.filter((w) => w.id !== id) }),
    [wf, workflows, id],
  );

  if (!user) return null;
  if (!wf || !catalog)
    return (
      <Page width="record">
        <PageHeader eyebrow="Admin / Settings / Workflow" back={{ href: "/admin/settings/workflows", label: "Workflows" }} title={error ? "Workflow" : "Loading workflow…"} />
        {error ? <ErrorState title={error} onRetry={() => void load()} /> : <LoadingState rows={6} label="Loading workflow" />}
      </Page>
    );

  const canEdit = can(user, P.workflowsManage);
  const byId = Object.fromEntries(wf.statuses.map((s) => [s.id, s]));
  const close = () => setOpen(null);
  const saved = () => {
    setOpen(null);
    void load();
  };

  const patchWorkflow = async (body: object) => {
    setError(null);
    try {
      await api.patch(`/api/lifecycle/workflows/${id}`, body);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "That didn't work.");
    }
  };

  const savePosition = (status: Status, at: { x: number; y: number }) => {
    const coordinates = `${Math.round(at.x)}|${Math.round(at.y)}`;
    if (coordinates === status.coordinates) return;
    setWf((w) => w && { ...w, statuses: w.statuses.map((s) => (s.id === status.id ? { ...s, coordinates } : s)) });
    api.post(`/api/lifecycle/statuses/${status.id}/position`, at).catch(() => setError("Couldn't save the new position."));
  };

  const selectedStatus = selected?.kind === "status" ? byId[selected.id] : undefined;
  const selectedTransition = selected?.kind === "transition" ? wf.transitions.find((t) => t.id === selected.id) : undefined;

  return (
    <div className="flex min-h-[80dvh] flex-col lg:h-[calc(100dvh-3.5rem)]">
      <PageHeader
        className="mb-0"
        eyebrow="Admin / Settings / Workflow"
        back={{ href: "/admin/settings/workflows", label: "Workflows" }}
        title={wf.name}
        meta={
          <>
            {wf.is_default && <Badge variant="info">Default for new tickets</Badge>}
            <span className="num text-xs">
              {wf.statuses.length} statuses · {wf.transitions.length} transitions · {wf.fields.length} fields
            </span>
          </>
        }
        actions={
        <div className="flex flex-wrap items-center gap-2 text-sm">
          <Button asChild variant="outline">
            <Link href={`/board?workflow=${wf.id}`}>
              Open board
            </Link>
          </Button>
          {canEdit && (
            <>
              <NativeSelect wrapperClassName="w-full sm:w-60"
                value={wf.transition_policy}
                onChange={(e) => void patchWorkflow({ transition_policy: e.target.value })}
                aria-label="Which moves are allowed"
              >
                <option value="strict">Only the drawn transitions</option>
                <option value="open">Any status to any status</option>
              </NativeSelect>
              {!wf.is_default && (
                <Button variant="outline" onClick={() => void patchWorkflow({ is_default: true })}>
                  Make default
                </Button>
              )}
            </>
          )}
        </div>
        }
      />

      {error && <ErrorState className="mt-3" title={error} />}

      <div className="mt-4 flex flex-wrap items-end justify-between gap-x-4">
        <Tabs
          value={tab}
          onChange={setTab}
          tabs={[
            { key: "diagram", label: "Diagram" },
            { key: "fields", label: "Fields", count: wf.fields.length },
          ]}
        />
        {canEdit && tab === "diagram" && (
          <div className="mb-3 flex flex-wrap gap-2">
            <Button variant="outline" onClick={() => setOpen({ kind: "status", status: null })}>
              Add status
            </Button>
            <Button variant="outline" onClick={() => setOpen({ kind: "transition", transition: null })}>
              Add transition
            </Button>
            <Button variant="outline" onClick={() => setOpen({ kind: "reorder" })}>
              Reorder
            </Button>
          </div>
        )}
        {canEdit && tab === "fields" && (
          <Button className="mb-3" onClick={() => setOpen({ kind: "field", field: null })}>
            Add field
          </Button>
        )}
      </div>

      {tab === "diagram" ? (
        <div className="grid min-h-0 flex-1 gap-4 lg:grid-cols-[1fr_320px]">
          <Card className="relative min-h-[420px] overflow-hidden">
            <WorkflowCanvas
              statuses={wf.statuses}
              transitions={wf.transitions}
              editable={canEdit}
              selected={selected}
              onSelect={setSelected}
              onMove={savePosition}
              onConnect={(c) => {
                if (byId[c.to]?.is_pipeline) {
                  setError(`${byId[c.to].name} is a triage status: only the pipeline moves tickets into it.`);
                  return;
                }
                setOpen({ kind: "transition", transition: null, draft: c });
              }}
              onEditStatus={(s) => canEdit && setOpen({ kind: "status", status: s })}
              onEditTransition={(t) => canEdit && setOpen({ kind: "transition", transition: t })}
            />
            {canEdit && (
              <p className="pointer-events-none absolute left-3 top-3 rounded-md bg-card/90 px-2 py-1 text-xs text-muted-foreground">
                Drag from a status's edge to another status to connect them. Double-click to edit.
              </p>
            )}
          </Card>
          <Card asChild>
            <aside className="min-h-0 overflow-y-auto">
              {selectedStatus ? (
                <StatusPanel
                  status={selectedStatus}
                  wf={wf}
                  catalog={catalog}
                  canEdit={canEdit}
                  onBack={() => setSelected(null)}
                  onEdit={() => setOpen({ kind: "status", status: selectedStatus })}
                  onDelete={() => setOpen({ kind: "delete", status: selectedStatus })}
                  onPickTransition={(t) => setSelected({ kind: "transition", id: t.id })}
                />
              ) : selectedTransition ? (
                <TransitionPanel
                  transition={selectedTransition}
                  wf={wf}
                  catalog={catalog}
                  canEdit={canEdit}
                  onBack={() => setSelected(null)}
                  onEdit={() => setOpen({ kind: "transition", transition: selectedTransition })}
                  onDelete={() => setOpen({ kind: "delete", transition: selectedTransition })}
                />
              ) : (
                <StatusList wf={wf} onPick={(s) => setSelected({ kind: "status", id: s.id })} />
              )}
            </aside>
          </Card>
        </div>
      ) : (
        <FieldsTable
          wf={wf}
          canEdit={canEdit}
          onEdit={(f) => setOpen({ kind: "field", field: f })}
          onDelete={async (f) => {
            if (!confirm(`Delete field "${f.name}"? Values on tickets are deleted too.`)) return;
            try {
              await api.delete(`/api/lifecycle/fields/${f.id}`);
              await load();
            } catch (err) {
              setError(err instanceof ApiError ? err.message : "That didn't work.");
            }
          }}
        />
      )}

      <StatusDialog
        open={open?.kind === "status"}
        onClose={close}
        onSaved={saved}
        workflow={wf}
        status={open?.kind === "status" ? open.status : null}
        catalog={catalog}
        context={context}
      />
      <TransitionDialog
        open={open?.kind === "transition"}
        onClose={close}
        onSaved={saved}
        workflow={wf}
        transition={open?.kind === "transition" ? open.transition : null}
        draft={open?.kind === "transition" ? open.draft : undefined}
        catalog={catalog}
        context={context}
      />
      <ReorderDialog open={open?.kind === "reorder"} onClose={close} onSaved={saved} workflow={wf} />
      <FieldDialog
        open={open?.kind === "field"}
        onClose={close}
        onSaved={saved}
        workflow={wf}
        field={open?.kind === "field" ? open.field : null}
        catalog={catalog}
        context={context}
      />
      <DeleteDialog
        open={open?.kind === "delete"}
        onClose={close}
        onDeleted={() => {
          setSelected(null);
          saved();
        }}
        workflow={wf}
        status={open?.kind === "delete" ? open.status : null}
        transition={open?.kind === "delete" ? open.transition : null}
      />
    </div>
  );
}

function PanelHeader({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <div className="flex items-center justify-between border-b border-border px-4 py-3">
      <h2 className="eyebrow !text-foreground/80">{title}</h2>
      <Button variant="ghost" size="xs" onClick={onBack} className="text-muted-foreground">
        All statuses
      </Button>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border px-4 py-3 last:border-0">
      <h3 className="mb-2 text-[11px] font-medium uppercase tracking-wider text-muted-foreground">{title}</h3>
      {children}
    </section>
  );
}

function ActionList({ actions, catalog, empty }: { actions: Action[]; catalog: Catalog; empty: string }) {
  if (actions.length === 0) return <p className="text-sm text-muted-foreground">{empty}</p>;
  return (
    <ol className="flex flex-col gap-1.5 text-sm">
      {actions.map((a, i) => (
        <li key={a.id ?? i} className={a.is_active ? "" : "text-muted-foreground line-through"}>
          <span className="mr-1.5 text-xs text-muted-foreground">{i + 1}.</span>
          {catalog.actions.find((s) => s.code === a.action)?.name ?? humanize(a.action)}
          {a.position !== "after" && <span className="ml-1.5 text-xs text-muted-foreground">({a.position === "both" ? "before & after" : a.position})</span>}
          {Object.values(a.params).some(Boolean) && (
            <span className="block truncate pl-5 font-mono text-xs text-muted-foreground">
              {Object.entries(a.params)
                .filter(([, v]) => v)
                .map(([k, v]) => `${k}=${v}`)
                .join(" · ")}
            </span>
          )}
        </li>
      ))}
    </ol>
  );
}

function StatusList({ wf, onPick }: { wf: WorkflowDetail; onPick: (s: Status) => void }) {
  const statuses = [...wf.statuses].sort((a, b) => a.order - b.order);
  return (
    <>
      <div className="border-b border-border px-4 py-3">
        <h2 className="eyebrow !text-foreground/80">Statuses</h2>
        <p className="text-xs text-muted-foreground">Select a status or transition to see what it does.</p>
      </div>
      <ul>
        {statuses.map((s) => {
          const out = wf.transitions.filter((t) => t.from_status_id === s.id || (t.is_bidirectional && t.to_status_id === s.id)).length;
          return (
            <li key={s.id}>
              <button onClick={() => onPick(s)} className="flex w-full items-center gap-3 px-4 py-2 text-left hover:bg-muted">
                <span className="w-5 text-xs text-muted-foreground">{s.order}</span>
                <span className="min-w-0 flex-1">
                  <StatusChip name={s.name} color={s.color} />
                  <span className="block truncate text-xs text-muted-foreground">
                    {KIND_LABEL[s.kind]}
                    {s.is_pipeline && " · triage"}
                  </span>
                </span>
                <span className="text-xs text-muted-foreground" title="Moves out">
                  {out} →
                </span>
              </button>
            </li>
          );
        })}
      </ul>
    </>
  );
}

function StatusPanel({
  status,
  wf,
  catalog,
  canEdit,
  onBack,
  onEdit,
  onDelete,
  onPickTransition,
}: {
  status: Status;
  wf: WorkflowDetail;
  catalog: Catalog;
  canEdit: boolean;
  onBack: () => void;
  onEdit: () => void;
  onDelete: () => void;
  onPickTransition: (t: Transition) => void;
}) {
  const byId = Object.fromEntries(wf.statuses.map((s) => [s.id, s]));
  const outgoing = wf.transitions.filter((t) => t.from_status_id === status.id);
  const incoming = wf.transitions.filter((t) => t.to_status_id === status.id);
  const row = (t: Transition, other: Status | undefined, arrow: string) => (
    <li key={t.id}>
      <button onClick={() => onPickTransition(t)} className="flex w-full items-center gap-2 rounded-md px-1 py-1 text-left text-sm hover:bg-muted">
        <span className="text-muted-foreground">{t.is_bidirectional ? "↔" : arrow}</span>
        <StatusChip name={other?.name ?? "?"} color={other?.color} />
        <span className="ml-auto truncate text-xs text-muted-foreground">{t.name}</span>
      </button>
    </li>
  );
  return (
    <>
      <PanelHeader title="Status" onBack={onBack} />
      <Section title="Status">
        <StatusChip name={status.name} color={status.color} />
        <dl className="mt-2 grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted-foreground">Counts as</dt>
          <dd>{KIND_LABEL[status.kind]}</dd>
          <dt className="text-muted-foreground">Key</dt>
          <dd className="font-mono text-xs leading-5">{status.key}</dd>
          <dt className="text-muted-foreground">Order</dt>
          <dd>{status.order}</dd>
        </dl>
        {status.is_pipeline && <p className="mt-2 text-xs text-muted-foreground">Triage status: only the triage pipeline moves tickets into it.</p>}
      </Section>
      {!status.is_pipeline && (
        <Section title="On enter">
          <ActionList actions={status.actions} catalog={catalog} empty="Nothing runs." />
        </Section>
      )}
      <Section title={`Moves out (${outgoing.length})`}>
        {outgoing.length ? <ul>{outgoing.map((t) => row(t, byId[t.to_status_id], "→"))}</ul> : <p className="text-sm text-muted-foreground">None.</p>}
      </Section>
      <Section title={`Moves in (${incoming.length})`}>
        {incoming.length ? <ul>{incoming.map((t) => row(t, byId[t.from_status_id], "←"))}</ul> : <p className="text-sm text-muted-foreground">None.</p>}
      </Section>
      {canEdit && (
        <div className="flex gap-2 px-4 py-3">
          <Button variant="outline" className="flex-1" onClick={onEdit}>
            Edit
          </Button>
          {!status.is_pipeline && (
            <Button variant="outline" className="flex-1 text-danger" onClick={onDelete}>
              Delete
            </Button>
          )}
        </div>
      )}
    </>
  );
}

function TransitionPanel({
  transition,
  wf,
  catalog,
  canEdit,
  onBack,
  onEdit,
  onDelete,
}: {
  transition: Transition;
  wf: WorkflowDetail;
  catalog: Catalog;
  canEdit: boolean;
  onBack: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const byId = Object.fromEntries(wf.statuses.map((s) => [s.id, s]));
  const fieldName = Object.fromEntries(wf.fields.map((f) => [f.id, f.name]));
  const from = byId[transition.from_status_id];
  const to = byId[transition.to_status_id];
  return (
    <>
      <PanelHeader title="Transition" onBack={onBack} />
      <Section title={transition.name}>
        <span className="inline-flex flex-wrap items-center gap-2">
          <StatusChip name={from?.name ?? "?"} color={from?.color} />
          <span className="text-muted-foreground">{transition.is_bidirectional ? "↔" : "→"}</span>
          <StatusChip name={to?.name ?? "?"} color={to?.color} />
        </span>
        {transition.is_bidirectional && <p className="mt-1.5 text-xs text-muted-foreground">Tickets can move both ways.</p>}
      </Section>
      <Section title={`Checks (${transition.rules.length})`}>
        {transition.rules.length ? (
          <ul className="flex flex-col gap-1 text-sm">
            {transition.rules.map((r, i) => (
              <li key={r.id ?? i} className={r.is_active ? "" : "text-muted-foreground line-through"}>
                <span className="font-medium">{fieldName[r.field_id] ?? "?"}</span> {catalog.rules.find((s) => s.code === r.rule)?.name.toLowerCase() ?? r.rule}
                {Object.values(r.params).some(Boolean) && <span className="font-mono text-xs text-muted-foreground"> {Object.values(r.params).join(", ")}</span>}
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">No checks.</p>
        )}
      </Section>
      <Section title={`Actions (${transition.actions.length})`}>
        <ActionList actions={transition.actions} catalog={catalog} empty="Nothing runs." />
      </Section>
      {canEdit && (
        <div className="flex gap-2 px-4 py-3">
          <Button variant="outline" className="flex-1" onClick={onEdit}>
            Edit
          </Button>
          <Button variant="outline" className="flex-1 text-danger" onClick={onDelete}>
            Delete
          </Button>
        </div>
      )}
    </>
  );
}

function FieldsTable({
  wf,
  canEdit,
  onEdit,
  onDelete,
}: {
  wf: WorkflowDetail;
  canEdit: boolean;
  onEdit: (f: Field) => void;
  onDelete: (f: Field) => void;
}) {
  if (wf.fields.length === 0) {
    return (
      <Card className="px-6 py-12 text-center text-sm text-muted-foreground">
        No fields yet. Fields hold extra information on tickets in this workflow; transitions can require them.
      </Card>
    );
  }
  return (
    <Card className="overflow-hidden">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Field</TableHead>
            <TableHead>Type</TableHead>
            <TableHead>Checks</TableHead>
            <TableHead>When it changes</TableHead>
            <TableHead />
          </TableRow>
        </TableHeader>
        <TableBody>
          {[...wf.fields]
            .sort((a, b) => a.order - b.order)
            .map((f) => (
              <TableRow key={f.id}>
                <TableCell className="py-3 font-medium">{f.name}</TableCell>
                <TableCell className="py-3 text-muted-foreground">
                  {humanize(f.field_type)}
                  {f.options.length > 0 && <span className="block text-xs">{f.options.join(", ")}</span>}
                </TableCell>
                <TableCell className="py-3 text-muted-foreground">{f.rules.length || "—"}</TableCell>
                <TableCell className="py-3 text-muted-foreground">
                  {f.events.length ? f.events.map((e) => `${humanize(e.event)} (${e.actions.length})`).join(", ") : "—"}
                </TableCell>
                <TableCell className="py-3 text-right">
                  {canEdit && (
                    <span className="flex justify-end gap-3 text-xs">
                      <Button variant="link" size="inline"  onClick={() => onEdit(f)}>
                        Edit
                      </Button>
                      <Button variant="link" size="inline" className="text-danger" onClick={() => onDelete(f)}>
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
  );
}
