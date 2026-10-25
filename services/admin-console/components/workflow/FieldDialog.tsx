"use client";

// Adds or edits a workflow's custom field: its type, its own checks, and what runs when it changes.

import { useEffect, useState } from "react";
import Modal, { Labeled, Tabs } from "@/components/Modal";
import { ActionsEditor, IconButton, cleanActions, stripEmpty, type ActionContext } from "@/components/workflow/Editors";
import { api, ApiError } from "@/lib/api";
import { humanize } from "@/lib/format";
import type { Catalog, Field, FieldEvent, Rule, WorkflowDetail } from "@/lib/lifecycle";

type FieldRule = Omit<Rule, "field_id">;

export default function FieldDialog({
  open,
  onClose,
  onSaved,
  workflow,
  field,
  catalog,
  context,
}: {
  open: boolean;
  onClose: () => void;
  onSaved: () => void;
  workflow: WorkflowDetail;
  field: Field | null;
  catalog: Catalog;
  context: ActionContext;
}) {
  const [tab, setTab] = useState<"info" | "rules" | "events">("info");
  const [name, setName] = useState("");
  const [type, setType] = useState("text");
  const [options, setOptions] = useState("");
  const [rules, setRules] = useState<FieldRule[]>([]);
  const [events, setEvents] = useState<FieldEvent[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setTab("info");
    setError(null);
    setName(field?.name ?? "");
    setType(field?.field_type ?? "text");
    setOptions(field?.options.join(", ") ?? "");
    setRules(field?.rules ?? []);
    setEvents(field?.events ?? []);
  }, [open, field]);

  const ruleChoices = catalog.rules.filter((r) => r.field_types.includes(type));

  const save = async () => {
    setBusy(true);
    setError(null);
    const body = {
      name: name.trim(),
      options: type === "select" ? options.split(",").map((o) => o.trim()).filter(Boolean) : [],
      rules: rules.map(({ rule, params, is_active }) => ({ rule, params: stripEmpty(params), is_active })),
      events: events.map(({ event, params, is_active, actions }) => ({ event, params: stripEmpty(params), is_active, actions: cleanActions(actions) })),
    };
    try {
      if (field) await api.patch(`/api/lifecycle/fields/${field.id}`, body);
      else await api.post(`/api/lifecycle/workflows/${workflow.id}/fields`, { ...body, field_type: type, order: workflow.fields.length });
      onSaved();
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
      title={field ? `Edit ${field.name}` : "Add a field"}
      width="max-w-2xl"
      footer={
        <>
          <button className="btn btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={busy || !name.trim()} onClick={save}>
            {field ? "Save" : "Add field"}
          </button>
        </>
      }
    >
      {error && <p className="tone-danger mb-3 rounded-[5px] px-3 py-2 text-sm">{error}</p>}
      <Tabs
        value={tab}
        onChange={setTab}
        tabs={[
          { key: "info", label: "Field" },
          { key: "rules", label: "Checks", count: rules.length },
          { key: "events", label: "When it changes", count: events.length },
        ]}
      />
      {tab === "info" && (
        <div className="grid gap-4">
          <Labeled label="Name">
            <input className="field" value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Resolution note" autoFocus />
          </Labeled>
          <Labeled label="Type" hint={field ? "The type can't change once tickets may hold values." : undefined}>
            <select className="field" value={type} onChange={(e) => setType(e.target.value)} disabled={!!field}>
              {catalog.field_types.map((t) => (
                <option key={t} value={t}>
                  {humanize(t)}
                </option>
              ))}
            </select>
          </Labeled>
          {type === "select" && (
            <Labeled label="Options" hint="Comma-separated.">
              <input className="field" value={options} onChange={(e) => setOptions(e.target.value)} placeholder="Hardware, Software, Access" />
            </Labeled>
          )}
        </div>
      )}
      {tab === "rules" && (
        <div className="flex flex-col gap-3">
          <p className="text-sm text-[var(--text-muted)]">Checked whenever someone sets the field.</p>
          {rules.map((r, i) => {
            const spec = catalog.rules.find((s) => s.code === r.rule);
            const update = (patch: Partial<FieldRule>) => setRules(rules.map((x, j) => (j === i ? { ...x, ...patch } : x)));
            return (
              <div key={i} className="flex flex-wrap items-center gap-2 rounded-[6px] border border-[var(--border)] bg-[var(--surface-2)] p-3">
                <select className="field min-w-0 flex-1" value={r.rule} onChange={(e) => update({ rule: e.target.value, params: {} })}>
                  {ruleChoices.map((s) => (
                    <option key={s.code} value={s.code}>
                      {s.name}
                    </option>
                  ))}
                </select>
                {spec?.params.map((p) => (
                  <input
                    key={p}
                    className="field w-40"
                    placeholder={p === "values" ? "a, b, c" : p}
                    value={r.params[p] ?? ""}
                    onChange={(e) => update({ params: { ...r.params, [p]: e.target.value } })}
                  />
                ))}
                <IconButton label="Remove" onClick={() => setRules(rules.filter((_, j) => j !== i))}>
                  ×
                </IconButton>
              </div>
            );
          })}
          <div>
            <button
              type="button"
              className="btn btn-secondary"
              disabled={ruleChoices.length === 0}
              onClick={() => setRules([...rules, { rule: ruleChoices[0].code, params: {}, is_active: true }])}
            >
              Add check
            </button>
          </div>
        </div>
      )}
      {tab === "events" && (
        <div className="flex flex-col gap-4">
          {events.length === 0 && <p className="text-sm text-[var(--text-muted)]">Nothing runs when this field changes.</p>}
          {events.map((ev, i) => {
            const spec = catalog.events.find((s) => s.code === ev.event);
            const update = (patch: Partial<FieldEvent>) => setEvents(events.map((x, j) => (j === i ? { ...x, ...patch } : x)));
            return (
              <div key={i} className="rounded-[6px] border border-[var(--border)] p-3">
                <div className="mb-3 flex flex-wrap items-center gap-2">
                  <span className="text-sm">When</span>
                  <select className="field w-48" value={ev.event} onChange={(e) => update({ event: e.target.value, params: {} })}>
                    {catalog.events.map((s) => (
                      <option key={s.code} value={s.code}>
                        {s.name.toLowerCase()}
                      </option>
                    ))}
                  </select>
                  {spec?.params.map((p) => (
                    <input key={p} className="field w-40" placeholder={p} value={ev.params[p] ?? ""} onChange={(e) => update({ params: { ...ev.params, [p]: e.target.value } })} />
                  ))}
                  <span className="flex-1" />
                  <IconButton label="Remove event" onClick={() => setEvents(events.filter((_, j) => j !== i))}>
                    ×
                  </IconButton>
                </div>
                <ActionsEditor actions={ev.actions} onChange={(actions) => update({ actions })} catalog={catalog} where="event" context={context} />
              </div>
            );
          })}
          <div>
            <button type="button" className="btn btn-secondary" onClick={() => setEvents([...events, { event: catalog.events[0].code, params: {}, is_active: true, actions: [] }])}>
              Add event
            </button>
          </div>
        </div>
      )}
    </Modal>
  );
}
