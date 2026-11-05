"use client";

// One person's record (F14): profile, status, every grant with its scope and end date, and what they can do and why.

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";
import Modal, { Labeled } from "@/components/Modal";
import { Badge, type Tone } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Page, PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { formatDate, relativeTime } from "@/lib/format";
import { END_REASON_LABEL, P, SCOPE_LABEL, UNGRANTABLE_ROLES, can, shortUrn } from "@/lib/permissions";
import type {
  AccountOut,
  AssignmentOut,
  DepartmentOut,
  PermissionOut,
  PersonAccessOut,
  PersonRecordOut,
  RoleOut,
  TeamOut,
} from "@/lib/types/generated";

const STATUS_TONE: Record<string, Tone> = { invited: "info", active: "ok", suspended: "warn", deactivated: "neutral" };
type StatusAction = "suspend" | "reactivate" | "deactivate";

interface GrantDraft {
  role: string;
  scope_kind: string;
  scope: string;
  ends_at: string;
  reason: string;
}

interface Profile {
  first_name: string;
  last_name: string;
  job_title: string;
  location: string;
  phone: string;
  employee_id: string;
  department: string;
  line_manager: string;
  reason: string;
}

export default function PersonPage() {
  const user = useRequireAuth();
  const toast = useToast();
  const params = useParams<{ username: string }>();
  const username = decodeURIComponent(params.username);
  const path = encodeURIComponent(username);

  const [person, setPerson] = useState<PersonRecordOut | null>(null);
  const [grants, setGrants] = useState<AssignmentOut[] | null>(null);
  const [access, setAccess] = useState<PersonAccessOut | null>(null);
  const [roles, setRoles] = useState<RoleOut[]>([]);
  const [catalogue, setCatalogue] = useState<PermissionOut[]>([]);
  const [teams, setTeams] = useState<TeamOut[]>([]);
  const [departments, setDepartments] = useState<DepartmentOut[]>([]);
  const [people, setPeople] = useState<AccountOut[]>([]);
  const [showEnded, setShowEnded] = useState(false);
  const [filter, setFilter] = useState("");
  const [grantDraft, setGrantDraft] = useState<GrantDraft | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);
  const [statusAction, setStatusAction] = useState<StatusAction | null>(null);
  const [rowAction, setRowAction] = useState<{ kind: "end" | "extend" | "confirm"; row: AssignmentOut; ends_at: string; reason: string } | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const canReadAccess = can(user, P.accessRead);

  const load = useCallback(async () => {
    try {
      const p = await api.get<PersonRecordOut>(`/api/accounts/people/${path}`);
      setPerson(p);
      setError(null);
      if (canReadAccess) {
        const [g, a] = await Promise.all([
          api.get<AssignmentOut[]>(`/api/access/people/${path}/assignments?include_ended=${showEnded}`),
          api.get<PersonAccessOut>(`/api/access/people/${path}/access`),
        ]);
        setGrants(g);
        setAccess(a);
      }
    } catch (err) {
      setError(err instanceof ApiError && err.status === 404 ? "No such person." : "Couldn't load this person.");
    }
  }, [path, showEnded, canReadAccess]);

  useEffect(() => {
    if (!user) return;
    void load();
  }, [user, load]);

  useEffect(() => {
    if (!user) return;
    void Promise.all([
      api.get<RoleOut[]>("/api/access/roles").catch(() => []),
      api.get<PermissionOut[]>("/api/access/permissions").catch(() => []),
      api.get<TeamOut[]>("/api/teams").catch(() => []),
      api.get<DepartmentOut[]>("/api/org/departments").catch(() => []),
      api.get<AccountOut[]>("/api/accounts/people").catch(() => []),
    ]).then(([r, c, t, d, p]) => {
      setRoles(r);
      setCatalogue(c);
      setTeams(t);
      setDepartments(d);
      setPeople(p);
    });
  }, [user]);

  const label = useMemo(() => new Map(catalogue.map((p) => [p.urn, p.label])), [catalogue]);
  const grantable = roles.filter((r) => !r.retired_at && !UNGRANTABLE_ROLES.has(r.urn));
  const chosen = roles.find((r) => r.urn === grantDraft?.role);

  if (!user) return null;
  const self = username === user.username;
  const canGrant = can(user, P.accessGrant) && !self;
  const canManagePeople = can(user, P.peopleManage) && !self;

  const changeStatus = async () => {
    if (!statusAction) return;
    setFormError(null);
    try {
      await api.post(`/api/accounts/people/${path}/${statusAction}`, { reason });
      toast.success({ suspend: "Suspended", reactivate: "Reactivated", deactivate: "Deactivated" }[statusAction]);
      setStatusAction(null);
      setReason("");
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't change their status.");
    }
  };

  const saveProfile = async () => {
    if (!profile) return;
    setFormError(null);
    try {
      await api.patch(`/api/accounts/people/${path}`, profile);
      toast.success("Profile saved");
      setProfile(null);
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't save the profile.");
    }
  };

  const grant = async () => {
    if (!grantDraft) return;
    setFormError(null);
    try {
      await api.post(`/api/access/people/${path}/assignments`, {
        role: grantDraft.role,
        scope_kind: grantDraft.scope_kind,
        scope: grantDraft.scope_kind === "global" ? null : grantDraft.scope,
        reason: grantDraft.reason,
        ends_at: grantDraft.ends_at ? new Date(`${grantDraft.ends_at}T23:59:59`).toISOString() : null,
      });
      toast.success("Granted; their sign-ins ended so it applies at once");
      setGrantDraft(null);
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't grant the role.");
    }
  };

  const actOnRow = async () => {
    if (!rowAction) return;
    setFormError(null);
    try {
      const body =
        rowAction.kind === "extend"
          ? { ends_at: rowAction.ends_at ? new Date(`${rowAction.ends_at}T23:59:59`).toISOString() : null, reason: rowAction.reason }
          : { reason: rowAction.reason };
      await api.post(`/api/access/assignments/${rowAction.row.id}/${rowAction.kind}`, body);
      toast.success({ end: "Grant ended", extend: "End date set", confirm: "Grant kept" }[rowAction.kind]);
      setRowAction(null);
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't change the grant.");
    }
  };

  const effective = (access?.permissions ?? []).filter((p) => {
    const q = filter.trim().toLowerCase();
    return !q || p.urn.includes(q) || (label.get(p.urn) ?? "").toLowerCase().includes(q);
  });

  return (
    <Page width="record" className="flex flex-col gap-4">
      <PageHeader
        back={{ href: "/admin/settings/people", label: "People" }}
        eyebrow="Admin / People & access"
        title={person ? person.name || person.username : username}
        meta={
          person && (
            <>
              <span className="font-mono">{person.username}</span>
              <Badge variant={STATUS_TONE[person.status ?? "active"] ?? "neutral"}>{person.status}</Badge>
              <span className="capitalize">{person.role}</span>
              {person.department && <span>{person.department.name}</span>}
              {person.is_break_glass && <Badge variant="warn">break-glass</Badge>}
            </>
          )
        }
        actions={
          person &&
          canManagePeople &&
          !person.is_break_glass && (
            <>
              {(person.status === "suspended" || person.status === "deactivated") && (
                <Button variant="outline" onClick={() => setStatusAction("reactivate")}>
                  Reactivate
                </Button>
              )}
              {(person.status === "active" || person.status === "invited") && (
                <Button variant="outline" onClick={() => setStatusAction("suspend")}>
                  Suspend
                </Button>
              )}
              {person.status !== "deactivated" && (
                <Button variant="outline" className="text-danger" onClick={() => setStatusAction("deactivate")}>
                  Deactivate
                </Button>
              )}
            </>
          )
        }
      />

      {error && <ErrorState title={error} onRetry={() => void load()} />}
      {!person && !error && <LoadingState rows={5} />}

      {person && (
        <>
          <Panel
            title="Profile"
            aside={
              canManagePeople && (
                <Button
                  size="sm"
                  variant="outline"
                  onClick={() => {
                    setFormError(null);
                    setProfile({
                      first_name: person.first_name,
                      last_name: person.last_name,
                      job_title: person.job_title ?? "",
                      location: person.location,
                      phone: person.phone,
                      employee_id: person.employee_id,
                      department: person.department?.code ?? "",
                      line_manager: person.line_manager ?? "",
                      reason: "",
                    });
                  }}
                >
                  Edit
                </Button>
              )
            }
          >
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[130px_1fr_130px_1fr]">
              <dt className="text-muted-foreground">Email</dt>
              <dd>{person.email || "—"}</dd>
              <dt className="text-muted-foreground">Job title</dt>
              <dd>{person.job_title || "—"}</dd>
              <dt className="text-muted-foreground">Department</dt>
              <dd>{person.department ? `${person.department.name} (${person.department.code})` : "—"}</dd>
              <dt className="text-muted-foreground">Line manager</dt>
              <dd>{person.line_manager ?? "—"}</dd>
              <dt className="text-muted-foreground">Location</dt>
              <dd>{person.location || "—"}</dd>
              <dt className="text-muted-foreground">Employee ID</dt>
              <dd>{person.employee_id || "—"}</dd>
              <dt className="text-muted-foreground">Sign-in</dt>
              <dd>{person.is_break_glass ? "Break-glass" : person.auth_source === "oidc" ? "Company" : "Local"}</dd>
              <dt className="text-muted-foreground">Last signed in</dt>
              <dd>{person.last_login ? relativeTime(person.last_login) : "never"}</dd>
              <dt className="text-muted-foreground">Teams</dt>
              <dd className="sm:col-span-3">
                {person.teams.length === 0 ? "—" : person.teams.map((t) => `${t.team}${t.role === "lead" ? " (lead)" : ""}`).join(", ")}
              </dd>
            </dl>
          </Panel>

          {canReadAccess && (
            <Panel
              title="Grants"
              flush
              aside={
                <>
                  <label className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Checkbox checked={showEnded} onCheckedChange={(on) => setShowEnded(on === true)} />
                    Show ended
                  </label>
                  {canGrant && person.is_active && (
                    <Button
                      size="sm"
                      onClick={() => {
                        setFormError(null);
                        setGrantDraft({ role: "", scope_kind: "global", scope: "", ends_at: "", reason: "" });
                      }}
                    >
                      Grant a role
                    </Button>
                  )}
                </>
              }
            >
              <p className="px-4 pt-3 text-xs text-muted-foreground sm:px-5">
                Base role <span className="font-medium capitalize text-foreground">{person.role}</span> applies everywhere and is set from the People
                list. Team-lead and department-head grants follow the team and the department.
              </p>
              <div className="overflow-x-auto">
                <Table className="min-w-[760px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Role</TableHead>
                      <TableHead>Scope</TableHead>
                      <TableHead>Granted</TableHead>
                      <TableHead>Ends</TableHead>
                      <TableHead />
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {grants && grants.length === 0 && (
                      <TableRow>
                        <TableCell colSpan={5} className="p-0">
                          <EmptyState compact title="No grants beyond the base role" />
                        </TableCell>
                      </TableRow>
                    )}
                    {(grants ?? []).map((g) => (
                      <TableRow key={g.id} className={g.active ? "" : "text-muted-foreground"}>
                        <TableCell>
                          <span className="font-medium">{g.role_name}</span>
                          {g.source === "structural" && <Badge variant="neutral" className="ml-1.5">structural</Badge>}
                          {g.needs_review && <Badge variant="warn" className="ml-1.5">needs review</Badge>}
                          <span className="block font-mono text-[11px] text-muted-foreground">{shortUrn(g.role)}</span>
                        </TableCell>
                        <TableCell>{g.scope}</TableCell>
                        <TableCell>
                          {formatDate(g.starts_at)}
                          <span className="block text-xs text-muted-foreground">{[g.granted_by, g.reason].filter(Boolean).join(" · ")}</span>
                        </TableCell>
                        <TableCell>
                          {g.ended_at ? (
                            <span>
                              ended {formatDate(g.ended_at)}
                              <span className="block text-xs">{END_REASON_LABEL[g.ended_reason] ?? g.ended_reason}</span>
                            </span>
                          ) : g.ends_at ? (
                            formatDate(g.ends_at)
                          ) : (
                            "—"
                          )}
                          {g.needs_review && g.review_due_at && <span className="block text-xs text-warn">ends {formatDate(g.review_due_at)} unless confirmed</span>}
                        </TableCell>
                        <TableCell className="text-right">
                          {canGrant && g.active && g.source !== "structural" && (
                            <span className="flex justify-end gap-1">
                              {g.needs_review && (
                                <Button size="xs" variant="outline" onClick={() => setRowAction({ kind: "confirm", row: g, ends_at: "", reason: "" })}>
                                  Keep
                                </Button>
                              )}
                              <Button
                                size="xs"
                                variant="outline"
                                onClick={() => setRowAction({ kind: "extend", row: g, ends_at: g.ends_at?.slice(0, 10) ?? "", reason: "" })}
                              >
                                End date
                              </Button>
                              <Button size="xs" variant="outline" className="text-danger" onClick={() => setRowAction({ kind: "end", row: g, ends_at: "", reason: "" })}>
                                End
                              </Button>
                            </span>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Panel>
          )}

          {canReadAccess && access && (
            <Panel
              title={`What they can do · ${access.permissions.length}`}
              flush
              aside={<Input className="h-8 w-56" placeholder="Filter permissions" value={filter} onChange={(e) => setFilter(e.target.value)} />}
            >
              <div className="overflow-x-auto">
                <Table className="min-w-[720px]">
                  <TableHeader>
                    <TableRow>
                      <TableHead>Permission</TableHead>
                      <TableHead>Where</TableHead>
                      <TableHead>Because of</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {effective.map((p) => (
                      <TableRow key={p.urn}>
                        <TableCell>
                          {label.get(p.urn) ?? shortUrn(p.urn)}
                          <span className="block font-mono text-[11px] text-muted-foreground">{shortUrn(p.urn)}</span>
                        </TableCell>
                        <TableCell className="text-sm">
                          {p.scope.everywhere
                            ? "Everywhere"
                            : [...p.scope.teams.map((t) => `team ${t}`), ...p.scope.departments.map((d) => `dept ${d}`)].join(", ") || "—"}
                        </TableCell>
                        <TableCell className="text-sm">
                          {p.sources.map((s, i) => (
                            <span key={i} className="block">
                              {s.role_name} <span className="text-muted-foreground">at {s.scope}</span>
                              {s.granted_by && <span className="text-muted-foreground"> · by {s.granted_by}</span>}
                              {s.ends_at && <span className="text-muted-foreground"> · until {formatDate(s.ends_at)}</span>}
                            </span>
                          ))}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </div>
            </Panel>
          )}
        </>
      )}

      <Modal
        open={!!grantDraft}
        onClose={() => setGrantDraft(null)}
        title={`Grant ${username} a role`}
        footer={
          grantDraft && (
            <Button
              disabled={!grantDraft.role || !grantDraft.reason.trim() || (grantDraft.scope_kind !== "global" && !grantDraft.scope)}
              onClick={() => void grant()}
            >
              Grant
            </Button>
          )
        }
      >
        {grantDraft && (
          <div className="flex flex-col gap-3 text-sm">
            <Labeled label="Role" required>
              <NativeSelect value={grantDraft.role} onChange={(e) => setGrantDraft({ ...grantDraft, role: e.target.value, scope_kind: "global", scope: "" })}>
                <option value="">Choose a role…</option>
                {grantable.map((r) => (
                  <option key={r.urn} value={r.urn}>
                    {r.name} {r.is_system ? "" : "(custom)"}
                  </option>
                ))}
              </NativeSelect>
            </Labeled>
            {chosen && (
              <Labeled label="Scope" required hint={chosen.scopes.length === 1 ? "This role is granted everywhere only." : undefined}>
                <NativeSelect value={grantDraft.scope_kind} onChange={(e) => setGrantDraft({ ...grantDraft, scope_kind: e.target.value, scope: "" })}>
                  {chosen.scopes.map((s) => (
                    <option key={s} value={s}>
                      {SCOPE_LABEL[s] ?? s}
                    </option>
                  ))}
                </NativeSelect>
              </Labeled>
            )}
            {grantDraft.scope_kind === "team" && (
              <Labeled label="Team" required>
                <NativeSelect value={grantDraft.scope} onChange={(e) => setGrantDraft({ ...grantDraft, scope: e.target.value })}>
                  <option value="">Choose a team…</option>
                  {teams.filter((t) => t.is_active).map((t) => (
                    <option key={t.slug} value={t.slug}>
                      {t.name}
                    </option>
                  ))}
                </NativeSelect>
              </Labeled>
            )}
            {grantDraft.scope_kind === "department" && (
              <Labeled label="Department" required>
                <NativeSelect value={grantDraft.scope} onChange={(e) => setGrantDraft({ ...grantDraft, scope: e.target.value })}>
                  <option value="">Choose a department…</option>
                  {departments.map((d) => (
                    <option key={d.code} value={d.code}>
                      {d.name} ({d.code})
                    </option>
                  ))}
                </NativeSelect>
              </Labeled>
            )}
            <Labeled label="Ends" hint="Leave empty for no end date. Cover for a holiday ends on its own.">
              <Input type="date" value={grantDraft.ends_at} onChange={(e) => setGrantDraft({ ...grantDraft, ends_at: e.target.value })} />
            </Labeled>
            <Labeled label="Reason" required>
              <Input value={grantDraft.reason} maxLength={500} placeholder="Kept in the audit log" onChange={(e) => setGrantDraft({ ...grantDraft, reason: e.target.value })} />
            </Labeled>
            {formError && <ErrorState compact title={formError} />}
          </div>
        )}
      </Modal>

      <Modal
        open={!!rowAction}
        onClose={() => setRowAction(null)}
        title={rowAction ? { end: `End ${rowAction.row.role_name}?`, extend: "Set the end date", confirm: `Keep ${rowAction.row.role_name}?` }[rowAction.kind] : ""}
        footer={
          rowAction && (
            <Button variant={rowAction.kind === "end" ? "destructive" : "default"} disabled={!rowAction.reason.trim()} onClick={() => void actOnRow()}>
              {{ end: "End now", extend: "Save", confirm: "Keep the grant" }[rowAction.kind]}
            </Button>
          )
        }
      >
        {rowAction && (
          <div className="flex flex-col gap-3 text-sm">
            <p className="text-muted-foreground">
              {rowAction.row.role_name} at {rowAction.row.scope}
            </p>
            {rowAction.kind === "extend" && (
              <Labeled label="Ends" hint="Empty for no end date.">
                <Input type="date" value={rowAction.ends_at} onChange={(e) => setRowAction({ ...rowAction, ends_at: e.target.value })} />
              </Labeled>
            )}
            <Labeled label="Reason" required>
              <Input value={rowAction.reason} maxLength={500} onChange={(e) => setRowAction({ ...rowAction, reason: e.target.value })} />
            </Labeled>
            {formError && <ErrorState compact title={formError} />}
          </div>
        )}
      </Modal>

      <Modal
        open={!!profile}
        onClose={() => setProfile(null)}
        title="Edit profile"
        size="xl"
        footer={
          profile && (
            <Button disabled={!profile.reason.trim()} onClick={() => void saveProfile()}>
              Save profile
            </Button>
          )
        }
      >
        {profile && (
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            {(
              [
                ["first_name", "First name"],
                ["last_name", "Last name"],
                ["job_title", "Job title"],
                ["location", "Location"],
                ["phone", "Phone"],
                ["employee_id", "Employee ID"],
              ] as const
            ).map(([key, text]) => (
              <Labeled key={key} label={text}>
                <Input value={profile[key]} onChange={(e) => setProfile({ ...profile, [key]: e.target.value })} />
              </Labeled>
            ))}
            <Labeled label="Department" hint="A move flags their department-scoped grants for review.">
              <NativeSelect value={profile.department} onChange={(e) => setProfile({ ...profile, department: e.target.value })}>
                {departments.map((d) => (
                  <option key={d.code} value={d.code}>
                    {d.name} ({d.code})
                  </option>
                ))}
              </NativeSelect>
            </Labeled>
            <Labeled label="Line manager">
              <NativeSelect value={profile.line_manager} onChange={(e) => setProfile({ ...profile, line_manager: e.target.value })}>
                <option value="">None</option>
                {people
                  .filter((p) => p.username !== username && p.is_active)
                  .map((p) => (
                    <option key={p.username} value={p.username}>
                      {p.username}
                    </option>
                  ))}
              </NativeSelect>
            </Labeled>
            <Labeled label="Reason" required className="sm:col-span-2">
              <Input value={profile.reason} maxLength={500} onChange={(e) => setProfile({ ...profile, reason: e.target.value })} />
            </Labeled>
            {formError && <ErrorState compact title={formError} className="sm:col-span-2" />}
          </div>
        )}
      </Modal>

      <Modal
        open={!!statusAction}
        onClose={() => setStatusAction(null)}
        title={statusAction ? { suspend: `Suspend ${username}?`, reactivate: `Reactivate ${username}?`, deactivate: `Deactivate ${username}?` }[statusAction] : ""}
        footer={
          statusAction && (
            <Button variant={statusAction === "reactivate" ? "default" : "destructive"} disabled={!reason.trim()} onClick={() => void changeStatus()}>
              {{ suspend: "Suspend", reactivate: "Reactivate", deactivate: "Deactivate" }[statusAction]}
            </Button>
          )
        }
      >
        {statusAction && (
          <div className="flex flex-col gap-3 text-sm">
            <p className="text-muted-foreground">
              {
                {
                  suspend: "They're signed out and can't sign in. Grants and teams stay.",
                  reactivate: "They can sign in again. A leaver's grants stay ended.",
                  deactivate: "They're signed out, leave every team, lose every grant and headship, and their open tickets go back to their team's queue.",
                }[statusAction]
              }
            </p>
            <Labeled label="Reason" required>
              <Input value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />
            </Labeled>
            {formError && <ErrorState compact title={formError} />}
          </div>
        )}
      </Modal>
    </Page>
  );
}
