"use client";

// Lists of actions and rules edited in place, driven by the lifecycle catalog.

import type { Action, Catalog, Field, Rule, Status } from "@/lib/lifecycle";
import { humanize } from "@/lib/format";

export interface ActionContext {
  fields: Field[];
  statuses: Status[];
  workflows: { id: string; name: string }[];
}

type Where = "transition" | "status" | "event";

const PHASE_OF: Record<Where, string[]> = {
  transition: ["before", "after"],
  status: ["enter"],
  event: ["event"],
};

export function ActionsEditor({
  actions,
  onChange,
  catalog,
  where,
  context,
}: {
  actions: Action[];
  onChange: (actions: Action[]) => void;
  catalog: Catalog;
  where: Where;
  context: ActionContext;
}) {
  const available = catalog.actions.filter((a) => a.phases.some((p) => PHASE_OF[where].includes(p)));
  const update = (i: number, patch: Partial<Action>) => onChange(actions.map((a, j) => (j === i ? { ...a, ...patch } : a)));

  return (
    <div className="flex flex-col gap-3">
      {actions.length === 0 && (
        <p className="text-sm text-[var(--text-muted)]">
          {where === "status" ? "Nothing runs when a ticket enters this status." : where === "event" ? "Nothing runs on this event." : "Nothing runs on this move."}
        </p>
      )}
      {actions.map((a, i) => {
        const spec = catalog.actions.find((s) => s.code === a.action);
        const positions = (["before", "after", "both"] as const).filter((p) =>
          p === "both" ? spec?.phases.includes("before") && spec?.phases.includes("after") : spec?.phases.includes(p),
        );
        return (
          <div key={i} className="rounded-[6px] border border-[var(--border)] bg-[var(--surface-2)] p-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="w-5 text-xs text-[var(--text-muted)]">{i + 1}.</span>
              <select
                className="field min-w-0 flex-1"
                value={a.action}
                onChange={(e) => update(i, { action: e.target.value, params: {}, position: defaultPosition(catalog, e.target.value) })}
              >
                {available.map((s) => (
                  <option key={s.code} value={s.code}>
                    {s.name}
                  </option>
                ))}
              </select>
              {where === "transition" && (
                <select className="field w-44" value={a.position} onChange={(e) => update(i, { position: e.target.value as Action["position"] })}>
                  {positions.map((p) => (
                    <option key={p} value={p}>
                      {p === "before" ? "Before the move" : p === "after" ? "After the move" : "Before and after"}
                    </option>
                  ))}
                </select>
              )}
              <label className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                <input type="checkbox" checked={a.is_active} onChange={(e) => update(i, { is_active: e.target.checked })} />
                On
              </label>
              <span className="flex gap-1">
                <IconButton label="Move up" disabled={i === 0} onClick={() => onChange(swap(actions, i, i - 1))}>
                  ↑
                </IconButton>
                <IconButton label="Move down" disabled={i === actions.length - 1} onClick={() => onChange(swap(actions, i, i + 1))}>
                  ↓
                </IconButton>
                <IconButton label="Remove" onClick={() => onChange(actions.filter((_, j) => j !== i))}>
                  ×
                </IconButton>
              </span>
            </div>
            {spec && (
              <>
                <p className="ml-7 mt-1.5 text-xs text-[var(--text-muted)]">
                  {spec.description}
                  {spec.blocking && " Waits for an answer before the move continues."}
                </p>
                <div className="ml-7 mt-2 grid gap-2 sm:grid-cols-2">
                  {spec.params.map((p) => (
                    <div key={p.name} className={p.type === "textarea" ? "sm:col-span-2" : ""}>
                      <ParamInput
                        param={p}
                        value={a.params[p.name] ?? ""}
                        onChange={(v) => update(i, { params: { ...a.params, [p.name]: v } })}
                        context={context}
                        actionCode={a.action}
                      />
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        );
      })}
      <div className="flex items-center justify-between">
        <button
          type="button"
          className="btn btn-secondary"
          disabled={available.length === 0}
          onClick={() =>
            onChange([...actions, { action: available[0].code, params: {}, position: defaultPosition(catalog, available[0].code), is_active: true }])
          }
        >
          Add action
        </button>
        <Placeholders variables={catalog.variables} />
      </div>
    </div>
  );
}

function defaultPosition(catalog: Catalog, code: string): Action["position"] {
  const spec = catalog.actions.find((s) => s.code === code);
  return spec && !spec.phases.includes("after") && spec.phases.includes("before") ? "before" : "after";
}

function ParamInput({
  param,
  value,
  onChange,
  context,
  actionCode,
}: {
  param: Catalog["actions"][number]["params"][number];
  value: string;
  onChange: (v: string) => void;
  context: ActionContext;
  actionCode: string;
}) {
  const label = (
    <span className="text-xs text-[var(--text-muted)]">
      {param.description}
      {!param.required && " (optional)"}
    </span>
  );
  let input;
  if (param.type === "textarea") {
    input = <textarea className="field min-h-20 font-mono text-[13px]" value={value} onChange={(e) => onChange(e.target.value)} />;
  } else if (param.type === "customfield") {
    input = (
      <select className="field" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose a field…</option>
        {context.fields.map((f) => (
          <option key={f.id} value={f.name}>
            {f.name}
          </option>
        ))}
      </select>
    );
  } else if (param.type === "workflowstatus" && actionCode !== "change_workflow") {
    input = (
      <select className="field" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose a status…</option>
        {context.statuses
          .filter((s) => !s.is_pipeline)
          .map((s) => (
            <option key={s.id} value={s.key}>
              {s.name}
            </option>
          ))}
      </select>
    );
  } else if (param.type === "workflow") {
    input = (
      <select className="field" value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">Choose a workflow…</option>
        {context.workflows.map((w) => (
          <option key={w.id} value={w.name}>
            {w.name}
          </option>
        ))}
      </select>
    );
  } else {
    input = <input className="field" value={value} onChange={(e) => onChange(e.target.value)} placeholder={param.type === "user" ? "username" : undefined} />;
  }
  return (
    <label className="flex flex-col gap-1">
      {label}
      {input}
    </label>
  );
}

export function Placeholders({ variables }: { variables: Record<string, string> }) {
  return (
    <details className="relative text-xs">
      <summary className="cursor-pointer text-[var(--text-muted)] hover:text-[var(--text)]">Placeholders</summary>
      <div className="absolute bottom-6 right-0 z-10 max-h-72 w-96 overflow-y-auto rounded-[6px] border border-[var(--border)] bg-[var(--surface)] p-3 shadow-lg">
        <p className="mb-2 text-[var(--text-muted)]">
          Write <code className="font-mono">{"{{ticket.id}}"}</code> in any text to insert the value.
        </p>
        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
          {Object.entries(variables).map(([k, v]) => (
            <div key={k} className="contents">
              <dt className="font-mono">{k}</dt>
              <dd className="text-[var(--text-muted)]">{v}</dd>
            </div>
          ))}
        </dl>
      </div>
    </details>
  );
}

export function RulesEditor({
  rules,
  onChange,
  catalog,
  fields,
}: {
  rules: Rule[];
  onChange: (rules: Rule[]) => void;
  catalog: Catalog;
  fields: Field[];
}) {
  const update = (i: number, patch: Partial<Rule>) => onChange(rules.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  if (fields.length === 0) {
    return <p className="text-sm text-[var(--text-muted)]">Checks test the ticket's fields. Add a field to this workflow first.</p>;
  }

  return (
    <div className="flex flex-col gap-3">
      {rules.length === 0 && <p className="text-sm text-[var(--text-muted)]">Anyone allowed to move the ticket can make this move.</p>}
      {rules.map((r, i) => {
        const field = fields.find((f) => f.id === r.field_id);
        const choices = catalog.rules.filter((s) => !field || s.field_types.includes(field.field_type));
        const spec = catalog.rules.find((s) => s.code === r.rule);
        return (
          <div key={i} className="rounded-[6px] border border-[var(--border)] bg-[var(--surface-2)] p-3">
            <div className="flex flex-wrap items-center gap-2">
              <select
                className="field min-w-0 flex-1"
                value={r.field_id}
                onChange={(e) => {
                  const f = fields.find((x) => x.id === e.target.value);
                  const ok = catalog.rules.find((s) => s.code === r.rule)?.field_types.includes(f?.field_type ?? "");
                  update(i, { field_id: e.target.value, ...(ok ? {} : { rule: "required", params: {} }) });
                }}
              >
                {fields.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                  </option>
                ))}
              </select>
              <select className="field min-w-0 flex-1" value={r.rule} onChange={(e) => update(i, { rule: e.target.value, params: {} })}>
                {choices.map((s) => (
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
                  onChange={(e) => update(i, { params: { ...r.params, [p]: e.target.value } })}
                  aria-label={humanize(p)}
                />
              ))}
              <label className="flex items-center gap-1.5 text-xs text-[var(--text-muted)]">
                <input type="checkbox" checked={r.is_active} onChange={(e) => update(i, { is_active: e.target.checked })} />
                On
              </label>
              <IconButton label="Remove" onClick={() => onChange(rules.filter((_, j) => j !== i))}>
                ×
              </IconButton>
            </div>
            {spec && <p className="mt-1.5 text-xs text-[var(--text-muted)]">{spec.description}</p>}
          </div>
        );
      })}
      <div>
        <button
          type="button"
          className="btn btn-secondary"
          onClick={() => onChange([...rules, { field_id: fields[0].id, rule: "required", params: {}, is_active: true }])}
        >
          Add check
        </button>
      </div>
    </div>
  );
}

export function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="grid h-7 w-7 place-items-center rounded-[4px] text-[var(--text-muted)] hover:bg-[var(--surface)] hover:text-[var(--text)] disabled:opacity-30"
    >
      {children}
    </button>
  );
}

function swap<T>(items: T[], a: number, b: number): T[] {
  const next = [...items];
  [next[a], next[b]] = [next[b], next[a]];
  return next;
}

export function cleanActions(actions: Action[]) {
  return actions.map(({ action, params, position, is_active }) => ({ action, params: stripEmpty(params), position, is_active }));
}

export function cleanRules(rules: Rule[]) {
  return rules.map(({ field_id, rule, params, is_active }) => ({ field_id, rule, params: stripEmpty(params), is_active }));
}

export function stripEmpty(params: Record<string, string>) {
  return Object.fromEntries(Object.entries(params).filter(([, v]) => v !== ""));
}
