"use client";

// Roles (F14, ADR-0045): the system roles code defines and the custom roles an access admin builds from permissions.

import { useCallback, useEffect, useMemo, useState } from "react";
import { Lock } from "lucide-react";
import Modal, { Labeled } from "@/components/Modal";
import { SectionTabs } from "@/components/TabNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Input } from "@/components/ui/input";
import { Page, PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { Textarea } from "@/components/ui/textarea";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { P, can, shortUrn } from "@/lib/permissions";
import type { PermissionOut, RoleOut } from "@/lib/types/generated";

interface Draft {
  urn: string | null;
  name: string;
  description: string;
  permissions: string[];
  reason: string;
}

const BLANK: Draft = { urn: null, name: "", description: "", permissions: [], reason: "" };

/** The URN a new custom role will get, as core-api makes it from the name. */
function urnFor(name: string): string {
  const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 48).replace(/-+$/, "");
  return `urn:smart-ticket:role:custom:${slug || "…"}`;
}

export default function RolesPage() {
  const user = useRequireAuth();
  const toast = useToast();
  const [roles, setRoles] = useState<RoleOut[] | null>(null);
  const [catalogue, setCatalogue] = useState<PermissionOut[]>([]);
  const [showRetired, setShowRetired] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [retiring, setRetiring] = useState<RoleOut | null>(null);
  const [retireReason, setRetireReason] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [r, c] = await Promise.all([
        api.get<RoleOut[]>(`/api/access/roles?include_retired=${showRetired}`),
        api.get<PermissionOut[]>("/api/access/permissions"),
      ]);
      setRoles(r);
      setCatalogue(c);
      setError(null);
    } catch {
      setError("Couldn't load the roles.");
    }
  }, [showRetired]);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  const byArea = useMemo(() => {
    const groups = new Map<string, PermissionOut[]>();
    for (const p of catalogue) groups.set(p.area, [...(groups.get(p.area) ?? []), p]);
    return [...groups.entries()];
  }, [catalogue]);
  const label = useMemo(() => new Map(catalogue.map((p) => [p.urn, p.label])), [catalogue]);

  if (!user) return null;
  const canManage = can(user, P.rolesManage);
  const mine = new Set(user.permissions ?? []);
  const viewing = roles?.find((r) => r.urn === open) ?? null;
  const system = roles?.filter((r) => r.is_system) ?? [];
  const custom = roles?.filter((r) => !r.is_system) ?? [];

  const save = async () => {
    if (!draft) return;
    setFormError(null);
    try {
      const body = { name: draft.name, description: draft.description, permissions: draft.permissions, reason: draft.reason };
      const saved = draft.urn
        ? await api.patch<RoleOut>(`/api/access/roles/${encodeURIComponent(draft.urn)}`, body)
        : await api.post<RoleOut>("/api/access/roles", body);
      toast.success(draft.urn ? `Saved ${saved.name}` : `Created ${saved.name}`);
      setDraft(null);
      setOpen(saved.urn);
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't save the role.");
    }
  };

  const retire = async () => {
    if (!retiring) return;
    try {
      await api.post(`/api/access/roles/${encodeURIComponent(retiring.urn)}/retire`, { reason: retireReason });
      toast.success(`Retired ${retiring.name}; its grants ended`);
      setOpen(null);
      setRetireReason("");
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't retire the role.");
      throw err;
    }
  };

  const toggle = (urn: string, on: boolean) =>
    draft && setDraft({ ...draft, permissions: on ? [...draft.permissions, urn] : draft.permissions.filter((x) => x !== urn) });

  const roleRow = (r: RoleOut) => (
    <li key={r.urn}>
      <button
        type="button"
        onClick={() => setOpen(r.urn)}
        className="flex w-full items-start justify-between gap-3 px-4 py-3 text-left hover:bg-muted/50 sm:px-5"
      >
        <span className="min-w-0">
          <span className="flex flex-wrap items-center gap-2 font-medium">
            {r.name}
            {r.retired_at && <Badge variant="neutral">retired</Badge>}
          </span>
          <span className="block truncate font-mono text-xs text-muted-foreground">{r.urn}</span>
          {r.description && <span className="mt-0.5 block text-xs text-muted-foreground">{r.description}</span>}
        </span>
        <span className="shrink-0 text-right text-xs text-muted-foreground">
          {r.permissions.length} permissions
          <span className="block">{r.holders} active grants</span>
        </span>
      </button>
    </li>
  );

  return (
    <Page width="record" className="flex flex-col gap-4">
      <SectionTabs className="mb-1" />
      <PageHeader
        className="mb-2"
        eyebrow="Admin / People & access"
        title="Roles"
        description="A role is a set of permissions, granted to a person everywhere, for one team or for a department and everything under it. System roles come from code; custom roles are built here."
        actions={
          <>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <Checkbox aria-label="Show retired" checked={showRetired} onCheckedChange={(on) => setShowRetired(on === true)} />
              Show retired
            </label>
            {canManage && (
              <Button
                onClick={() => {
                  setDraft({ ...BLANK });
                  setFormError(null);
                }}
              >
                New custom role
              </Button>
            )}
          </>
        }
      />

      {error && <ErrorState title={error} onRetry={() => void load()} />}
      {!roles && !error && <LoadingState rows={6} />}

      {roles && (
        <div className="grid gap-4 lg:grid-cols-2">
          <Panel title="System roles" aside={<span className="text-xs text-muted-foreground">read-only</span>} flush>
            <ul className="divide-y divide-border">{system.map(roleRow)}</ul>
          </Panel>
          <Panel title="Custom roles" flush>
            {custom.length === 0 ? (
              <EmptyState compact title="No custom roles yet">
                Copy a system role or start from nothing; locked permissions stay with the system roles.
              </EmptyState>
            ) : (
              <ul className="divide-y divide-border">{custom.map(roleRow)}</ul>
            )}
          </Panel>
        </div>
      )}

      <Modal
        open={!!viewing && !draft}
        onClose={() => setOpen(null)}
        title={viewing?.name ?? ""}
        subtitle={viewing ? <span className="font-mono text-xs">{viewing.urn}</span> : undefined}
        size="xl"
        footer={
          viewing && canManage ? (
            <div className="flex w-full flex-wrap justify-between gap-2">
              <Button
                variant="outline"
                onClick={() =>
                  setDraft({
                    urn: null,
                    name: `${viewing.name} copy`,
                    description: viewing.description,
                    permissions: viewing.permissions.filter((p) => !catalogue.find((c) => c.urn === p)?.locked),
                    reason: "",
                  })
                }
              >
                Copy
              </Button>
              {!viewing.is_system && !viewing.retired_at && (
                <span className="flex gap-2">
                  <Button variant="outline" className="text-danger" onClick={() => setRetiring(viewing)}>
                    Retire
                  </Button>
                  <Button
                    onClick={() =>
                      setDraft({ urn: viewing.urn, name: viewing.name, description: viewing.description, permissions: viewing.permissions, reason: "" })
                    }
                  >
                    Edit
                  </Button>
                </span>
              )}
            </div>
          ) : undefined
        }
      >
        {viewing && (
          <div className="flex flex-col gap-4 text-sm">
            {viewing.description && <p className="text-muted-foreground">{viewing.description}</p>}
            <p className="text-xs text-muted-foreground">
              Grantable at: {viewing.scopes.join(", ") || "—"} · {viewing.holders} active grants
            </p>
            {byArea.map(([area, perms]) => {
              const held = perms.filter((p) => viewing.permissions.includes(p.urn));
              if (held.length === 0) return null;
              return (
                <section key={area}>
                  <h3 className="eyebrow mb-1.5">{area}</h3>
                  <ul className="flex flex-col gap-1">
                    {held.map((p) => (
                      <li key={p.urn} className="flex items-baseline justify-between gap-3">
                        <span>
                          {p.label}
                          {p.locked && <Lock className="ml-1 inline size-3 text-muted-foreground" aria-label="locked" />}
                        </span>
                        <span className="truncate font-mono text-[11px] text-muted-foreground">{shortUrn(p.urn)}</span>
                      </li>
                    ))}
                  </ul>
                </section>
              );
            })}
          </div>
        )}
      </Modal>

      <Modal
        open={!!draft}
        onClose={() => setDraft(null)}
        title={draft?.urn ? `Edit ${draft.name}` : "New custom role"}
        subtitle={draft ? <span className="font-mono text-xs">{draft.urn ?? urnFor(draft.name)}</span> : undefined}
        size="2xl"
        footer={
          draft && (
            <div className="flex w-full flex-wrap items-center gap-2">
              <Input
                className="min-w-[240px] flex-1"
                placeholder="Reason (kept in the audit log)"
                maxLength={500}
                value={draft.reason}
                onChange={(e) => setDraft({ ...draft, reason: e.target.value })}
              />
              <Button disabled={!draft.reason.trim() || draft.name.trim().length < 2 || draft.permissions.length === 0} onClick={() => void save()}>
                {draft.urn ? "Save role" : "Create role"}
              </Button>
            </div>
          )
        }
      >
        {draft && (
          <div className="flex flex-col gap-4 text-sm">
            <div className="grid gap-3 sm:grid-cols-2">
              <Labeled label="Name" required hint={draft.urn ? "Renaming keeps the URN." : "The URN is made from the name and never changes."}>
                <Input value={draft.name} maxLength={120} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
              </Labeled>
              <Labeled label="Description">
                <Textarea rows={2} value={draft.description} maxLength={500} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
              </Labeled>
            </div>
            <p className="text-xs text-muted-foreground">
              Locked permissions come only from system roles. You can add only permissions you hold everywhere yourself.
            </p>
            <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2">
              {byArea.map(([area, perms]) => (
                <fieldset key={area} className="min-w-0">
                  <legend className="eyebrow mb-1.5">{area}</legend>
                  <div className="flex flex-col gap-1.5">
                    {perms.map((p) => {
                      const blocked = p.locked || (!mine.has(p.urn) && !draft.permissions.includes(p.urn));
                      return (
                        <label key={p.urn} className={`flex items-start gap-2 ${blocked ? "opacity-50" : ""}`} title={p.urn}>
                          <Checkbox
                            className="mt-0.5"
                            aria-label={p.label}
                            checked={draft.permissions.includes(p.urn)}
                            disabled={blocked}
                            onCheckedChange={(on) => toggle(p.urn, on === true)}
                          />
                          <span className="min-w-0">
                            {p.label}
                            {p.locked && <Lock className="ml-1 inline size-3" aria-label="locked" />}
                            {p.scopes.length > 1 && <span className="ml-1 text-xs text-muted-foreground">· scopable</span>}
                          </span>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>
              ))}
            </div>
            {draft.permissions.length > 0 && (
              <p className="text-xs text-muted-foreground">
                {draft.permissions.length} selected: {draft.permissions.map((u) => label.get(u) ?? shortUrn(u)).join(", ")}
              </p>
            )}
            {formError && <ErrorState compact title={formError} />}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!retiring}
        title={retiring ? `Retire ${retiring.name}?` : ""}
        confirmLabel="Retire and end its grants"
        destructive
        onConfirm={retire}
        onClose={() => setRetiring(null)}
      >
        <p className="mb-3 text-sm text-muted-foreground">
          Every active grant of this role ends now. Its URN stays reserved and is never reused.
        </p>
        <Input placeholder="Reason" value={retireReason} onChange={(e) => setRetireReason(e.target.value)} />
      </ConfirmDialog>
    </Page>
  );
}
