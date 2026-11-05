"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState } from "@/components/ui/states";

// People (ADR-0042, F14): every account, its status, department, role, capabilities and teams; new people are invited here.

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import Modal, { Labeled } from "@/components/Modal";
import { SectionTabs } from "@/components/TabNav";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { relativeTime } from "@/lib/format";
import { P, can } from "@/lib/permissions";
import type { AccountOut, Capability, DepartmentOut, TeamOut, UserRole } from "@/lib/types/generated";
import { useToast } from "@/components/ui/toast";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";

const ROLES: { value: UserRole; label: string; hint: string }[] = [
  { value: "employee", label: "Employee", hint: "Asks for help in chat and follows their own tickets." },
  { value: "technician", label: "Technician", hint: "Works tickets in the console." },
  { value: "manager", label: "Manager", hint: "Runs teams and the system, and sets people's roles." },
  { value: "security", label: "Security", hint: "Handles security alerts and personal-data access." },
];

const CAPABILITIES: { value: Capability; label: string; hint: string }[] = [
  { value: "workflow_admin", label: "Workflow admin", hint: "Edits workflows, SLAs, teams, notifications and runbooks." },
  { value: "kb_editor", label: "KB editor", hint: "Writes and reviews help-page drafts." },
  { value: "incident_manager", label: "Incident manager", hint: "Confirms mass incidents and updates everyone affected." },
];

const ROLE_LABEL = Object.fromEntries(ROLES.map((r) => [r.value, r.label]));
const CAP_LABEL = Object.fromEntries(CAPABILITIES.map((c) => [c.value, c.label]));

interface RightsDraft {
  role: UserRole;
  capabilities: Capability[];
  reason: string;
}

export default function PeoplePage() {
  const user = useRequireAuth();
  const [people, setPeople] = useState<AccountOut[] | null>(null);
  const [teams, setTeams] = useState<TeamOut[]>([]);
  const [query, setQuery] = useState("");
  const [roleFilter, setRoleFilter] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [rights, setRights] = useState<RightsDraft | null>(null);
  const [joining, setJoining] = useState({ team: "", role: "member" });
  const [error, setError] = useState<string | null>(null);
  const [departments, setDepartments] = useState<DepartmentOut[]>([]);
  const [statusFilter, setStatusFilter] = useState("");
  const [invite, setInvite] = useState<{ username: string; email: string; first_name: string; last_name: string; department: string; job_title: string; reason: string } | null>(null);
  const toast = useToast();

  const load = useCallback(async () => {
    try {
      const [p, t, d] = await Promise.all([
        api.get<AccountOut[]>("/api/accounts/people"),
        api.get<TeamOut[]>("/api/teams").catch(() => []),
        api.get<DepartmentOut[]>("/api/org/departments").catch(() => []),
      ]);
      setPeople(p);
      setTeams(t);
      setDepartments(d);
    } catch {
      setError("Couldn't load people.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  const shown = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (people ?? []).filter(
      (p) =>
        (!roleFilter || p.role === roleFilter) &&
        (!statusFilter || p.status === statusFilter) &&
        (!q || p.username.toLowerCase().includes(q) || p.name.toLowerCase().includes(q) || p.email.toLowerCase().includes(q)),
    );
  }, [people, query, roleFilter, statusFilter]);

  if (!user) return null;
  const isManager = user.role === "manager";
  const canEditTeams = isManager || (user.capabilities ?? []).includes("workflow_admin");
  const person = people?.find((p) => p.username === open) ?? null;
  const counts = Object.fromEntries(ROLES.map((r) => [r.value, (people ?? []).filter((p) => p.role === r.value).length]));

  const openPerson = (p: AccountOut) => {
    setOpen(p.username);
    setRights({ role: p.role as UserRole, capabilities: p.capabilities as Capability[], reason: "" });
    setJoining({ team: "", role: "member" });
    setError(null);
  };

  const saveRights = async () => {
    if (!person || !rights) return;
    setError(null);
    try {
      const body = { ...rights, capabilities: rights.role === "employee" ? [] : rights.capabilities };
      await api.put(`/api/accounts/people/${encodeURIComponent(person.username)}/rights`, body);
      await load();
      setRights({ ...rights, reason: "" });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change the rights.");
    }
  };

  const setMembership = async (team: string, role: string) => {
    if (!person) return;
    setError(null);
    try {
      await api.post(`/api/teams/${team}/members`, { username: person.username, role });
      setJoining({ team: "", role: "member" });
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't change the team.");
    }
  };

  const sendInvite = async () => {
    if (!invite) return;
    setError(null);
    try {
      await api.post("/api/accounts/people", { ...invite, department: invite.department || null });
      toast.success(`Invited ${invite.username}; they link on their first company sign-in`);
      setInvite(null);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't invite them.");
    }
  };

  const leave = async (team: string) => {
    if (!person) return;
    setError(null);
    try {
      await api.delete(`/api/teams/${team}/members/${encodeURIComponent(person.username)}`);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't remove them from the team.");
    }
  };

  const self = person?.username === user.username;
  const rightsLocked = !isManager || self || !person;
  const changed =
    !!person &&
    !!rights &&
    (rights.role !== person.role || [...rights.capabilities].sort().join() !== [...person.capabilities].sort().join());
  const isStaff = (role: string) => role !== "employee";
  const teamName = new Map(teams.map((t) => [t.slug, t.name]));

  return (
    <Page width="record" className="flex flex-col gap-4">
      <SectionTabs className="mb-1" />
      <PageHeader
        className="mb-2"
        eyebrow="Admin / People & access"
        title="People"
        description={<>Company sign-in proves who someone is; their department, role, capabilities and teams are set here. Open a person for their grants and what they can do.</>}
        actions={
      <>
      <div className="flex flex-wrap items-center gap-2">
        <Input className="w-64" placeholder="Search name, username or email" value={query} onChange={(e) => setQuery(e.target.value)} />
        <NativeSelect wrapperClassName="w-44" aria-label="Filter by role" value={roleFilter} onChange={(e) => setRoleFilter(e.target.value)}>
          <option value="">All roles ({people?.length ?? 0})</option>
          {ROLES.map((r) => (
            <option key={r.value} value={r.value}>
              {r.label} ({counts[r.value] ?? 0})
            </option>
          ))}
        </NativeSelect>
        <NativeSelect wrapperClassName="w-40" aria-label="Filter by status" value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}>
          <option value="">Any status</option>
          {["invited", "active", "suspended", "deactivated"].map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </NativeSelect>
        {can(user, P.peopleManage) && (
          <Button
            onClick={() => {
              setError(null);
              setInvite({ username: "", email: "", first_name: "", last_name: "", department: "", job_title: "", reason: "" });
            }}
          >
            Invite person
          </Button>
        )}
      </div>
      </>
      }
      />

      {error && !open && !invite && <ErrorState title={error} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[900px]">
          <TableHeader>
            <TableRow>
              <TableHead>Person</TableHead>
              <TableHead>Department</TableHead>
              <TableHead>Role</TableHead>
              <TableHead>Capabilities</TableHead>
              <TableHead>Teams</TableHead>
              <TableHead>Sign-in</TableHead>
              <TableHead>Last signed in</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {people && shown.length === 0 && (
              <TableRow>
                <TableCell colSpan={7} className="p-0">
                  <EmptyState compact title="Nobody matches" />
                </TableCell>
              </TableRow>
            )}
            {shown.map((p) => (
              <TableRow
                key={p.username}
                className={`cursor-pointer border-t border-border hover:bg-muted/50 ${p.is_active ? "" : "text-muted-foreground"}`}
                onClick={() => openPerson(p)}
              >
                <TableCell>
                  <span className="font-medium text-primary">{p.username}</span>
                  {p.username === user.username && <span className="text-xs text-muted-foreground"> · you</span>}
                  <span className="block text-xs text-muted-foreground">{[p.name, p.email].filter(Boolean).join(" · ") || "—"}</span>
                </TableCell>
                <TableCell>
                  {p.department?.name ?? "—"}
                  {p.job_title && <span className="block text-xs text-muted-foreground">{p.job_title}</span>}
                </TableCell>
                <TableCell>{ROLE_LABEL[p.role] ?? p.role}</TableCell>
                <TableCell>
                  <span className="flex flex-wrap gap-1">
                    {p.capabilities.length === 0 && <span className="text-muted-foreground">—</span>}
                    {p.capabilities.map((c) => (
                      <Badge key={c} variant="brand">
                        {CAP_LABEL[c] ?? c}
                      </Badge>
                    ))}
                  </span>
                </TableCell>
                <TableCell>
                  <span className="flex flex-wrap gap-1">
                    {p.teams.length === 0 && <span className="text-muted-foreground">—</span>}
                    {p.teams.map((t) => (
                      <Badge key={t.team} variant="neutral">
                        {teamName.get(t.team) ?? t.team}
                        {t.role === "lead" ? " · lead" : ""}
                      </Badge>
                    ))}
                  </span>
                </TableCell>
                <TableCell>
                  {p.is_break_glass ? "Break-glass" : p.auth_source === "oidc" ? "Company" : "Local"}
                  {p.status && p.status !== "active" && (
                    <Badge variant={p.status === "invited" ? "info" : p.status === "suspended" ? "warn" : "neutral"} className="ml-1.5">
                      {p.status}
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="text-muted-foreground">{p.last_login ? relativeTime(p.last_login) : "never"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Modal
        open={!!person}
        onClose={() => setOpen(null)}
        title={person ? person.username : ""}
        subtitle={person ? [person.name, person.email].filter(Boolean).join(" · ") || undefined : undefined}
        size="xl"
        footer={
          person ? (
            <Link className="text-sm font-medium text-primary hover:underline" href={`/admin/settings/people/${encodeURIComponent(person.username)}`}>
              Open the full record: profile, grants and what they can do →
            </Link>
          ) : undefined
        }
      >
        {person && rights && (
          <div className="flex flex-col gap-5 text-sm">
            <section className="flex flex-col gap-3">
              <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Role</h2>
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {ROLES.map((r) => (
                  <label
                    key={r.value}
                    className={`flex cursor-pointer gap-2 rounded-md border px-3 py-2 ${
                      rights.role === r.value ? "border-primary bg-primary-soft" : "border-border"
                    } ${rightsLocked || (person.is_break_glass && r.value !== "manager") ? "cursor-not-allowed opacity-60" : ""}`}
                  >
                    <input
                      type="radio"
                      name="role"
                      className="mt-1 accent-[var(--primary)]"
                      checked={rights.role === r.value}
                      disabled={rightsLocked || (person.is_break_glass && r.value !== "manager")}
                      onChange={() => setRights({ ...rights, role: r.value })}
                    />
                    <span>
                      <span className="font-medium">{r.label}</span>
                      <span className="block text-xs text-muted-foreground">{r.hint}</span>
                    </span>
                  </label>
                ))}
              </div>

              <h2 className="pt-1 text-xs font-medium uppercase tracking-wider text-muted-foreground">Capabilities</h2>
              <div className="flex flex-col gap-2">
                {CAPABILITIES.map((c) => (
                  <label key={c.value} className={`flex gap-2 ${rightsLocked || !isStaff(rights.role) ? "opacity-60" : ""}`}>
                    <Checkbox
                      className="mt-0.5"
                      checked={isStaff(rights.role) && rights.capabilities.includes(c.value)}
                      disabled={rightsLocked || !isStaff(rights.role)}
                      onCheckedChange={(on) =>
                        setRights({
                          ...rights,
                          capabilities: on === true ? [...rights.capabilities, c.value] : rights.capabilities.filter((x) => x !== c.value),
                        })
                      }
                    />
                    <span>
                      <span className="font-medium">{c.label}</span>
                      <span className="block text-xs text-muted-foreground">{c.hint}</span>
                    </span>
                  </label>
                ))}
              </div>

              {self && <p className="text-xs text-muted-foreground">Another manager changes your own role.</p>}
              {!isManager && <p className="text-xs text-muted-foreground">Only a manager changes roles and capabilities.</p>}
              {person.is_break_glass && <p className="text-xs text-muted-foreground">A break-glass account always stays a manager.</p>}
              {!rightsLocked && changed && (
                <div className="flex flex-col gap-2 rounded-md border border-border bg-background p-3">
                  {rights.role === "employee" && person.teams.length > 0 && (
                    <p className="text-xs text-warn">As an employee they leave every team: {person.teams.map((t) => t.team).join(", ")}.</p>
                  )}
                  <p className="text-xs text-muted-foreground">Saving signs them out everywhere so the change applies at once.</p>
                  <div className="flex flex-wrap items-center gap-2">
                    <Input
                      className="min-w-[240px] flex-1"
                      placeholder="Reason (kept in the audit log)"
                      maxLength={500}
                      value={rights.reason}
                      onChange={(e) => setRights({ ...rights, reason: e.target.value })}
                    />
                    <Button disabled={!rights.reason.trim()} onClick={() => void saveRights()}>
                      Save role
                    </Button>
                  </div>
                </div>
              )}
            </section>

            <section className="flex flex-col gap-2 border-t border-border pt-4">
              <h2 className="text-xs font-medium uppercase tracking-wider text-muted-foreground">Teams</h2>
              {person.teams.length === 0 && <p className="text-muted-foreground">Not in any team.</p>}
              <ul className="flex flex-col gap-1.5">
                {person.teams.map((t) => (
                  <li key={t.team} className="flex items-center justify-between gap-3">
                    <span>{teamName.get(t.team) ?? t.team}</span>
                    <span className="flex items-center gap-3">
                      {canEditTeams ? (
                        <NativeSelect
                          size="sm"
                          wrapperClassName="w-28"
                          aria-label={`Role in ${t.team}`}
                          value={t.role}
                          onChange={(e) => void setMembership(t.team, e.target.value)}
                        >
                          <option value="member">Member</option>
                          <option value="lead">Lead</option>
                        </NativeSelect>
                      ) : (
                        <span className="capitalize">{t.role}</span>
                      )}
                      {canEditTeams && (
                        <Button variant="link" size="inline" className="text-xs text-danger" onClick={() => void leave(t.team)}>
                          Remove
                        </Button>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
              {canEditTeams && isStaff(person.role) && person.is_active && (
                <div className="flex flex-wrap items-center gap-2 pt-1">
                  <NativeSelect
                    wrapperClassName="min-w-[200px] flex-1"
                    aria-label="Team to join"
                    value={joining.team}
                    onChange={(e) => setJoining({ ...joining, team: e.target.value })}
                  >
                    <option value="">Add to a team…</option>
                    {teams
                      .filter((t) => t.is_active && !person.teams.some((m) => m.team === t.slug))
                      .map((t) => (
                        <option key={t.slug} value={t.slug}>
                          {t.name}
                        </option>
                      ))}
                  </NativeSelect>
                  <NativeSelect
                    wrapperClassName="w-28"
                    aria-label="Role in the team"
                    value={joining.role}
                    onChange={(e) => setJoining({ ...joining, role: e.target.value })}
                  >
                    <option value="member">Member</option>
                    <option value="lead">Lead</option>
                  </NativeSelect>
                  <Button variant="outline" disabled={!joining.team} onClick={() => void setMembership(joining.team, joining.role)}>
                    Add
                  </Button>
                </div>
              )}
              {!isStaff(person.role) && <p className="text-xs text-muted-foreground">Employees aren't in teams; give them a staff role first.</p>}
            </section>

            {error && <p className="rounded-md bg-danger-soft px-3 py-2 text-danger">{error}</p>}
          </div>
        )}
      </Modal>
      <Modal
        open={!!invite}
        onClose={() => setInvite(null)}
        title="Invite a person"
        subtitle="They start as an employee and link to their company account by verified email at first sign-in."
        footer={
          invite && (
            <Button disabled={!invite.username.trim() || !invite.email.trim() || !invite.reason.trim()} onClick={() => void sendInvite()}>
              Invite
            </Button>
          )
        }
      >
        {invite && (
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            <Labeled label="Username" required>
              <Input value={invite.username} onChange={(e) => setInvite({ ...invite, username: e.target.value })} />
            </Labeled>
            <Labeled label="Work email" required>
              <Input type="email" value={invite.email} onChange={(e) => setInvite({ ...invite, email: e.target.value })} />
            </Labeled>
            <Labeled label="First name">
              <Input value={invite.first_name} onChange={(e) => setInvite({ ...invite, first_name: e.target.value })} />
            </Labeled>
            <Labeled label="Last name">
              <Input value={invite.last_name} onChange={(e) => setInvite({ ...invite, last_name: e.target.value })} />
            </Labeled>
            <Labeled label="Department">
              <NativeSelect value={invite.department} onChange={(e) => setInvite({ ...invite, department: e.target.value })}>
                <option value="">Default department</option>
                {departments.map((d) => (
                  <option key={d.code} value={d.code}>
                    {d.name} ({d.code})
                  </option>
                ))}
              </NativeSelect>
            </Labeled>
            <Labeled label="Job title">
              <Input value={invite.job_title} onChange={(e) => setInvite({ ...invite, job_title: e.target.value })} />
            </Labeled>
            <Labeled label="Reason" required className="sm:col-span-2">
              <Input value={invite.reason} placeholder="Kept in the audit log" onChange={(e) => setInvite({ ...invite, reason: e.target.value })} />
            </Labeled>
            {error && <ErrorState compact title={error} className="sm:col-span-2" />}
          </div>
        )}
      </Modal>
    </Page>
  );
}
