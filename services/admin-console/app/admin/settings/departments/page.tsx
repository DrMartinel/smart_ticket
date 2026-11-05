"use client";

// Departments (F14): the organisation's tree, each unit's head and cost centre, and CSV imports of units and people.

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import { ChevronRight, Upload } from "lucide-react";
import Modal, { Labeled, Tabs } from "@/components/Modal";
import { SectionTabs } from "@/components/TabNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Page, PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { P, can, canEverywhere, shortUrn } from "@/lib/permissions";
import type { AccountOut, AssignmentOut, DepartmentOut, ImportOut, RoleOut, StaffOut } from "@/lib/types/generated";

type Mode = "create" | "edit" | "move" | "archive";

interface Draft {
  mode: Mode;
  code: string;
  name: string;
  parent: string;
  head: string;
  cost_centre: string;
  reason: string;
}

type ImportKind = "departments" | "people";

const SAMPLE: Record<ImportKind, string> = {
  departments: "code,name,parent_code,head,cost_centre\nFIN,Finance,,,CC-210\nFIN-AP,Accounts payable,FIN,,CC-212",
  people: "username,email,first_name,last_name,department_code,line_manager,job_title,location,phone,employee_id\nthao.vt,thao.vt@example.com,Thao,Vu,FIN,,Finance lead,Hanoi,,E-1021",
};

export default function DepartmentsPage() {
  const user = useRequireAuth();
  const toast = useToast();
  const [rows, setRows] = useState<DepartmentOut[] | null>(null);
  const [people, setPeople] = useState<StaffOut[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [members, setMembers] = useState<AccountOut[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [importing, setImporting] = useState<{ kind: ImportKind; csv: string; reason: string; result: ImportOut | null } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [placing, setPlacing] = useState<{ username: string; reason: string } | null>(null);
  const [deptGrants, setDeptGrants] = useState<AssignmentOut[] | null>(null);
  const [delegable, setDelegable] = useState<RoleOut[]>([]);
  const [delegating, setDelegating] = useState<{ username: string; role: string; ends_at: string; reason: string } | null>(null);
  const [ending, setEnding] = useState<{ row: AssignmentOut; reason: string } | null>(null);
  const [refresh, setRefresh] = useState(0);

  const load = useCallback(async () => {
    try {
      const [d, p] = await Promise.all([
        api.get<DepartmentOut[]>("/api/org/departments"),
        api.get<AccountOut[]>("/api/accounts/people").catch(() => [] as AccountOut[]),
      ]);
      setRows(d);
      setPeople(p.filter((x) => x.is_active).map((x) => ({ username: x.username, role: x.role })));
      setError(null);
    } catch {
      setError("Couldn't load the departments.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  useEffect(() => {
    if (!selected || !can(user, P.departmentsRead)) return setMembers(null);
    api
      .get<AccountOut[]>(`/api/org/departments/${encodeURIComponent(selected)}/people`)
      .then(setMembers)
      .catch(() => setMembers([]));
  }, [selected, user, refresh]);

  useEffect(() => {
    if (!selected || !(can(user, P.grantDelegable) || can(user, P.accessRead))) return setDeptGrants(null);
    api
      .get<AssignmentOut[]>(`/api/org/departments/${encodeURIComponent(selected)}/grants`)
      .then(setDeptGrants)
      .catch(() => setDeptGrants(null));
  }, [selected, user, refresh]);

  useEffect(() => {
    if (!can(user, P.grantDelegable)) return;
    api
      .get<RoleOut[]>("/api/org/delegable-roles")
      .then(setDelegable)
      .catch(() => setDelegable([]));
  }, [user]);

  const tree = useMemo(() => {
    const children = new Map<string | null, DepartmentOut[]>();
    for (const d of rows ?? []) children.set(d.parent, [...(children.get(d.parent) ?? []), d]);
    const flat: { dept: DepartmentOut; depth: number }[] = [];
    const walk = (parent: string | null, depth: number) => {
      for (const d of (children.get(parent) ?? []).sort((a, b) => a.name.localeCompare(b.name))) {
        flat.push({ dept: d, depth });
        walk(d.code, depth + 1);
      }
    };
    walk(null, 0);
    return flat;
  }, [rows]);

  if (!user) return null;
  const canManage = can(user, P.departmentsManage);
  const manageEverywhere = canEverywhere(user, P.departmentsManage);
  const mayDelegate = can(user, P.grantDelegable);
  const canImport = can(user, P.orgImport);
  const current = rows?.find((d) => d.code === selected) ?? null;

  const open = (mode: Mode, d?: DepartmentOut) => {
    setFormError(null);
    setDraft({
      mode,
      code: d?.code ?? "",
      name: d?.name ?? "",
      parent: mode === "create" ? (d?.code ?? "") : (d?.parent ?? ""),
      head: d?.head ?? "",
      cost_centre: d?.cost_centre ?? "",
      reason: "",
    });
  };

  const submit = async () => {
    if (!draft) return;
    setFormError(null);
    const code = encodeURIComponent(draft.code);
    try {
      if (draft.mode === "create") {
        await api.post("/api/org/departments", {
          code: draft.code,
          name: draft.name,
          parent: draft.parent || null,
          head: draft.head || null,
          cost_centre: draft.cost_centre,
          reason: draft.reason,
        });
      } else if (draft.mode === "edit") {
        const before = rows?.find((d) => d.code === draft.code)?.head ?? "";
        await api.patch(`/api/org/departments/${code}`, {
          name: draft.name,
          ...(draft.head !== before ? { head: draft.head } : {}),
          cost_centre: draft.cost_centre,
          reason: draft.reason,
        });
      } else if (draft.mode === "move") {
        await api.post(`/api/org/departments/${code}/move`, { parent: draft.parent || null, reason: draft.reason });
      } else {
        await api.post(`/api/org/departments/${code}/archive`, { reason: draft.reason });
      }
      toast.success({ create: "Department created", edit: "Department saved", move: "Department moved", archive: "Department archived" }[draft.mode]);
      setSelected(draft.mode === "archive" ? null : draft.code.toUpperCase());
      setDraft(null);
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't save the department.");
    }
  };

  const act = async (call: () => Promise<unknown>, done: string, close: () => void) => {
    setFormError(null);
    try {
      await call();
      toast.success(done);
      close();
      setRefresh((n) => n + 1);
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't save the change.");
    }
  };

  const runImport = async (dryRun: boolean) => {
    if (!importing) return;
    setFormError(null);
    try {
      const result = await api.post<ImportOut>(`/api/org/import/${importing.kind}?dry_run=${dryRun}`, {
        csv: importing.csv,
        reason: importing.reason,
      });
      setImporting({ ...importing, result });
      if (result.applied) {
        toast.success(`Imported ${result.rows.filter((r) => r.action !== "unchanged").length} change(s)`);
        await load();
      }
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't read the file.");
    }
  };

  const readFile = (file: File | undefined) => {
    if (!file || !importing) return;
    void file.text().then((csv) => setImporting({ ...importing, csv, result: null }));
  };

  const descendants = (code: string): Set<string> => {
    const found = new Set([code]);
    let grew = true;
    while (grew) {
      grew = false;
      for (const d of rows ?? []) if (d.parent && found.has(d.parent) && !found.has(d.code)) (found.add(d.code), (grew = true));
    }
    return found;
  };

  return (
    <Page width="record" className="flex flex-col gap-4">
      <SectionTabs className="mb-1" />
      <PageHeader
        className="mb-2"
        eyebrow="Admin / People & access"
        title="Departments"
        description="Everyone belongs to one department. A head reads their department's tickets and answers access reviews for it; grants can be scoped to a department and everything under it."
        actions={
          <>
            {canImport && (
              <Button variant="outline" onClick={() => setImporting({ kind: "departments", csv: "", reason: "", result: null })}>
                <Upload className="size-4" aria-hidden /> Import CSV
              </Button>
            )}
            {canManage && <Button onClick={() => open("create")}>New department</Button>}
          </>
        }
      />

      {error && <ErrorState title={error} onRetry={() => void load()} />}
      {!rows && !error && <LoadingState rows={6} />}

      {rows && (
        <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.1fr)]">
          <Panel title={`Tree · ${rows.length}`} flush>
            {tree.length === 0 ? (
              <EmptyState compact title="No departments" />
            ) : (
              <ul className="py-1">
                {tree.map(({ dept, depth }) => (
                  <li key={dept.code}>
                    <button
                      type="button"
                      onClick={() => setSelected(dept.code)}
                      aria-current={selected === dept.code}
                      className={`flex w-full items-center gap-2 py-2 pr-4 text-left text-sm hover:bg-muted/50 ${selected === dept.code ? "bg-primary-soft" : ""}`}
                      style={{ paddingLeft: `${1 + depth * 1.25}rem` }}
                    >
                      {depth > 0 && <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" aria-hidden />}
                      <span className="min-w-0 flex-1 truncate">
                        <span className="font-medium">{dept.name}</span>
                        <span className="ml-2 font-mono text-xs text-muted-foreground">{dept.code}</span>
                      </span>
                      {dept.is_default && <Badge variant="neutral">default</Badge>}
                      <span className="text-xs tabular-nums text-muted-foreground">{dept.people}</span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          <Panel
            title={current ? current.name : "Department"}
            aside={
              current &&
              canManage && (
                <>
                  <Button size="sm" variant="outline" onClick={() => open("edit", current)}>
                    Edit
                  </Button>
                  {manageEverywhere && (
                    <Button size="sm" variant="outline" onClick={() => open("move", current)}>
                      Move
                    </Button>
                  )}
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      setFormError(null);
                      setPlacing({ username: "", reason: "" });
                    }}
                  >
                    Move a person here
                  </Button>
                  <Button size="sm" variant="outline" onClick={() => open("create", current)}>
                    Add below
                  </Button>
                  {manageEverywhere && !current.is_default && (
                    <Button size="sm" variant="outline" className="text-danger" onClick={() => open("archive", current)}>
                      Archive
                    </Button>
                  )}
                </>
              )
            }
          >
            {!current ? (
              <EmptyState compact title="Pick a department">Its head, cost centre and people show here.</EmptyState>
            ) : (
              <div className="flex flex-col gap-4 text-sm">
                <dl className="grid grid-cols-[110px_1fr] gap-x-3 gap-y-1.5">
                  <dt className="text-muted-foreground">Code</dt>
                  <dd className="font-mono">{current.code}</dd>
                  <dt className="text-muted-foreground">Parent</dt>
                  <dd>{current.parent ?? "—"}</dd>
                  <dt className="text-muted-foreground">Head</dt>
                  <dd>
                    {current.head ? (
                      <Link className="text-primary hover:underline" href={`/admin/settings/people/${encodeURIComponent(current.head)}`}>
                        {current.head}
                      </Link>
                    ) : (
                      "—"
                    )}
                  </dd>
                  <dt className="text-muted-foreground">Cost centre</dt>
                  <dd>{current.cost_centre || "—"}</dd>
                  <dt className="text-muted-foreground">People</dt>
                  <dd>{current.people}</dd>
                </dl>
                {members && (
                  <Table>
                    <TableHeader>
                      <TableRow>
                        <TableHead>Person</TableHead>
                        <TableHead>Role</TableHead>
                        <TableHead>Status</TableHead>
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {members.length === 0 && (
                        <TableRow>
                          <TableCell colSpan={3} className="text-muted-foreground">
                            Nobody here yet.
                          </TableCell>
                        </TableRow>
                      )}
                      {members.map((m) => (
                        <TableRow key={m.username}>
                          <TableCell>
                            <Link className="font-medium text-primary hover:underline" href={`/admin/settings/people/${encodeURIComponent(m.username)}`}>
                              {m.username}
                            </Link>
                            <span className="block text-xs text-muted-foreground">{[m.name, m.job_title].filter(Boolean).join(" · ")}</span>
                          </TableCell>
                          <TableCell className="capitalize">{m.role}</TableCell>
                          <TableCell className="capitalize">{m.status}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                )}
                {deptGrants && (
                  <section className="flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-2">
                      <h3 className="eyebrow">Grants scoped here and below</h3>
                      {mayDelegate && (
                        <Button
                          size="sm"
                          variant="outline"
                          disabled={delegable.length === 0}
                          title={delegable.length === 0 ? "No custom role is marked delegable" : undefined}
                          onClick={() => {
                            setFormError(null);
                            setDelegating({ username: "", role: delegable[0]?.urn ?? "", ends_at: "", reason: "" });
                          }}
                        >
                          Grant a role
                        </Button>
                      )}
                    </div>
                    <Table>
                      <TableHeader>
                        <TableRow>
                          <TableHead>Person</TableHead>
                          <TableHead>Role</TableHead>
                          <TableHead>At</TableHead>
                          <TableHead>Ends</TableHead>
                          <TableHead />
                        </TableRow>
                      </TableHeader>
                      <TableBody>
                        {deptGrants.length === 0 && (
                          <TableRow>
                            <TableCell colSpan={5} className="text-muted-foreground">
                              No grants scoped to this department.
                            </TableCell>
                          </TableRow>
                        )}
                        {deptGrants.map((g) => (
                          <TableRow key={g.id}>
                            <TableCell>{g.user}</TableCell>
                            <TableCell>
                              {g.role_name}
                              <span className="block font-mono text-xs text-muted-foreground">{shortUrn(g.role)}</span>
                            </TableCell>
                            <TableCell className="font-mono text-xs">{g.scope}</TableCell>
                            <TableCell className="text-xs">{g.ends_at ? new Date(g.ends_at).toLocaleDateString() : "—"}</TableCell>
                            <TableCell className="text-right">
                              {mayDelegate && delegable.some((r) => r.urn === g.role) && (
                                <Button
                                  variant="link"
                                  size="inline"
                                  className="text-xs text-danger"
                                  onClick={() => {
                                    setFormError(null);
                                    setEnding({ row: g, reason: "" });
                                  }}
                                >
                                  End
                                </Button>
                              )}
                            </TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </section>
                )}
              </div>
            )}
          </Panel>
        </div>
      )}

      <Modal
        open={!!draft}
        onClose={() => setDraft(null)}
        title={
          draft
            ? { create: "New department", edit: `Edit ${draft.code}`, move: `Move ${draft.code}`, archive: `Archive ${draft.code}` }[draft.mode]
            : ""
        }
        footer={
          draft && (
            <Button
              variant={draft.mode === "archive" ? "destructive" : "default"}
              disabled={!draft.reason.trim() || (draft.mode === "create" && (!draft.code.trim() || !draft.name.trim()))}
              onClick={() => void submit()}
            >
              {{ create: "Create", edit: "Save", move: "Move", archive: "Archive" }[draft.mode]}
            </Button>
          )
        }
      >
        {draft && (
          <div className="flex flex-col gap-3 text-sm">
            {draft.mode === "create" && (
              <Labeled label="Code" required hint="Capitals, digits and dashes; never changes.">
                <Input value={draft.code} maxLength={30} onChange={(e) => setDraft({ ...draft, code: e.target.value.toUpperCase() })} />
              </Labeled>
            )}
            {(draft.mode === "create" || draft.mode === "edit") && (
              <>
                <Labeled label="Name" required>
                  <Input value={draft.name} maxLength={120} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
                </Labeled>
                {manageEverywhere && (
                <Labeled label="Head" hint="The head is granted the department-head role over this department and everything under it.">
                  <NativeSelect value={draft.head} onChange={(e) => setDraft({ ...draft, head: e.target.value })}>
                    <option value="">No head</option>
                    {people.map((p) => (
                      <option key={p.username} value={p.username}>
                        {p.username}
                      </option>
                    ))}
                  </NativeSelect>
                </Labeled>
                )}
                <Labeled label="Cost centre">
                  <Input value={draft.cost_centre} maxLength={40} onChange={(e) => setDraft({ ...draft, cost_centre: e.target.value })} />
                </Labeled>
              </>
            )}
            {(draft.mode === "create" || draft.mode === "move") && (
              <Labeled label="Parent">
                <NativeSelect value={draft.parent} onChange={(e) => setDraft({ ...draft, parent: e.target.value })}>
                  <option value="">Top level</option>
                  {(rows ?? [])
                    .filter((d) => draft.mode === "create" || !descendants(draft.code).has(d.code))
                    .map((d) => (
                      <option key={d.code} value={d.code}>
                        {d.name} ({d.code})
                      </option>
                    ))}
                </NativeSelect>
              </Labeled>
            )}
            {draft.mode === "archive" && (
              <p className="text-muted-foreground">Only an empty department is archived. Grants scoped to it end.</p>
            )}
            <Labeled label="Reason" required>
              <Input value={draft.reason} maxLength={500} placeholder="Kept in the audit log" onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
            </Labeled>
            {formError && <ErrorState compact title={formError} />}
          </div>
        )}
      </Modal>

      <Modal
        open={!!placing}
        onClose={() => setPlacing(null)}
        title={current ? `Move a person into ${current.name}` : ""}
        subtitle="They keep their grants; a grant scoped to their old department may need a second look."
        footer={
          placing &&
          current && (
            <Button
              disabled={!placing.username.trim() || !placing.reason.trim()}
              onClick={() =>
                void act(
                  () => api.post(`/api/org/departments/${encodeURIComponent(current.code)}/people`, placing),
                  `Moved ${placing.username} to ${current.code}`,
                  () => setPlacing(null),
                )
              }
            >
              Move
            </Button>
          )
        }
      >
        {placing && (
          <div className="flex flex-col gap-3 text-sm">
            <Labeled label="Username" required hint="Someone in a department you look after.">
              <Input value={placing.username} onChange={(e) => setPlacing({ ...placing, username: e.target.value })} />
            </Labeled>
            <Labeled label="Reason" required>
              <Input value={placing.reason} maxLength={500} placeholder="Kept in the audit log" onChange={(e) => setPlacing({ ...placing, reason: e.target.value })} />
            </Labeled>
            {formError && <ErrorState compact title={formError} />}
          </div>
        )}
      </Modal>

      <Modal
        open={!!delegating}
        onClose={() => setDelegating(null)}
        title={current ? `Grant a role in ${current.name}` : ""}
        subtitle="Only roles marked delegable, to someone in your departments, scoped to this department and everything under it."
        footer={
          delegating &&
          current && (
            <Button
              disabled={!delegating.username.trim() || !delegating.role || !delegating.reason.trim()}
              onClick={() =>
                void act(
                  () =>
                    api.post(`/api/org/departments/${encodeURIComponent(current.code)}/grants`, {
                      username: delegating.username,
                      role: delegating.role,
                      reason: delegating.reason,
                      ends_at: delegating.ends_at ? new Date(delegating.ends_at).toISOString() : null,
                    }),
                  `Granted to ${delegating.username}`,
                  () => setDelegating(null),
                )
              }
            >
              Grant
            </Button>
          )
        }
      >
        {delegating && (
          <div className="flex flex-col gap-3 text-sm">
            <Labeled label="Person" required>
              {members ? (
                <NativeSelect value={delegating.username} onChange={(e) => setDelegating({ ...delegating, username: e.target.value })}>
                  <option value="">Pick someone…</option>
                  {members
                    .filter((m) => m.is_active && m.username !== user.username)
                    .map((m) => (
                      <option key={m.username} value={m.username}>
                        {m.username}
                      </option>
                    ))}
                </NativeSelect>
              ) : (
                <Input value={delegating.username} onChange={(e) => setDelegating({ ...delegating, username: e.target.value })} />
              )}
            </Labeled>
            <Labeled label="Role" required>
              <NativeSelect value={delegating.role} onChange={(e) => setDelegating({ ...delegating, role: e.target.value })}>
                {delegable.map((r) => (
                  <option key={r.urn} value={r.urn}>
                    {r.name}
                  </option>
                ))}
              </NativeSelect>
            </Labeled>
            <Labeled label="Ends" hint="Leave empty for no end date; the access review still asks about it.">
              <Input type="date" value={delegating.ends_at} onChange={(e) => setDelegating({ ...delegating, ends_at: e.target.value })} />
            </Labeled>
            <Labeled label="Reason" required>
              <Input value={delegating.reason} maxLength={500} placeholder="Kept in the audit log" onChange={(e) => setDelegating({ ...delegating, reason: e.target.value })} />
            </Labeled>
            {formError && <ErrorState compact title={formError} />}
          </div>
        )}
      </Modal>

      <Modal
        open={!!ending}
        onClose={() => setEnding(null)}
        title={ending ? `End ${ending.row.role_name} for ${ending.row.user}` : ""}
        size="sm"
        footer={
          ending &&
          current && (
            <Button
              variant="destructive"
              disabled={!ending.reason.trim()}
              onClick={() =>
                void act(
                  () =>
                    api.post(`/api/org/departments/${encodeURIComponent(current.code)}/grants/${ending.row.id}/end`, { reason: ending.reason }),
                  "Grant ended",
                  () => setEnding(null),
                )
              }
            >
              End grant
            </Button>
          )
        }
      >
        {ending && (
          <div className="flex flex-col gap-3 text-sm">
            <Labeled label="Reason" required>
              <Input value={ending.reason} maxLength={500} placeholder="Kept in the audit log" onChange={(e) => setEnding({ ...ending, reason: e.target.value })} />
            </Labeled>
            {formError && <ErrorState compact title={formError} />}
          </div>
        )}
      </Modal>

      <Modal
        open={!!importing}
        onClose={() => setImporting(null)}
        title="Import CSV"
        subtitle="Checked first; applied only when every row passes."
        size="2xl"
        footer={
          importing && (
            <div className="flex w-full flex-wrap items-center gap-2">
              <Input
                className="min-w-[220px] flex-1"
                placeholder="Reason (kept in the audit log)"
                value={importing.reason}
                onChange={(e) => setImporting({ ...importing, reason: e.target.value })}
              />
              <Button variant="outline" disabled={!importing.csv.trim() || !importing.reason.trim()} onClick={() => void runImport(true)}>
                Check
              </Button>
              <Button
                disabled={!importing.result || importing.result.applied || importing.result.rows.some((r) => r.errors.length > 0)}
                onClick={() => void runImport(false)}
              >
                Apply
              </Button>
            </div>
          )
        }
      >
        {importing && (
          <div className="flex flex-col gap-3 text-sm">
            <Tabs<ImportKind>
              tabs={[
                { key: "departments", label: "Departments" },
                { key: "people", label: "People" },
              ]}
              value={importing.kind}
              onChange={(kind) => setImporting({ ...importing, kind, result: null })}
            />
            <input type="file" accept=".csv,text/csv" className="text-sm" onChange={(e) => readFile(e.target.files?.[0])} />
            <Textarea
              rows={6}
              className="font-mono text-xs"
              placeholder={SAMPLE[importing.kind]}
              value={importing.csv}
              onChange={(e) => setImporting({ ...importing, csv: e.target.value, result: null })}
            />
            {importing.result && (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Line</TableHead>
                    <TableHead>Row</TableHead>
                    <TableHead>Result</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {importing.result.rows.map((r) => (
                    <TableRow key={r.line}>
                      <TableCell className="tabular-nums">{r.line}</TableCell>
                      <TableCell className="font-mono text-xs">{r.key}</TableCell>
                      <TableCell>
                        {r.errors.length ? (
                          <span className="text-danger">{r.errors.join("; ")}</span>
                        ) : (
                          <Badge variant={r.action === "create" ? "ok" : r.action === "update" ? "info" : "neutral"}>{r.action}</Badge>
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
            {importing.result?.applied && <p className="text-ok">Applied.</p>}
            {formError && <ErrorState compact title={formError} />}
          </div>
        )}
      </Modal>
    </Page>
  );
}
