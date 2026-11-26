"use client";

// Ticket categories (ADR-0049): each category, what it means, the team that owns it and the workflow its
// tickets move into; rename, reorder and choose the workflow, and for a manager, what it means and whether
// it is routed automatically.

import { useCallback, useEffect, useState } from "react";
import Modal, { Labeled } from "@/components/Modal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { forgetCategories } from "@/lib/categories";
import type { Workflow } from "@/lib/lifecycle";
import { P, can } from "@/lib/permissions";
import type { CategoryOut, CategoryPatch, TeamOut } from "@/lib/types/generated";

interface Draft {
  slug: string;
  name: string;
  sort_order: string;
  description: string;
  is_routable: boolean;
  workflow: string;
  reason: string;
}

export default function CategoriesPage() {
  const user = useRequireAuth();
  const [categories, setCategories] = useState<CategoryOut[] | null>(null);
  const [owners, setOwners] = useState<Record<string, string>>({});
  const [teamsFailed, setTeamsFailed] = useState(false);
  const [workflows, setWorkflows] = useState<Workflow[] | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [all, teams, flows] = await Promise.all([
        api.get<CategoryOut[]>("/api/categories"),
        api.get<TeamOut[]>("/api/teams").catch(() => null),
        api.get<Workflow[]>("/api/lifecycle/workflows").catch(() => null),
      ]);
      setCategories(all);
      setTeamsFailed(teams === null);
      setWorkflows(flows);
      setOwners(
        Object.fromEntries((teams ?? []).filter((t) => t.is_active).flatMap((t) => t.categories.map((c) => [c, t.name]))),
      );
    } catch {
      setError("Couldn't load the categories.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;
  const canEdit = can(user, P.categoriesManage);
  const canDefine = can(user, P.categoriesDefine);
  const workflowName = (id: string | null | undefined) => workflows?.find((w) => w.id === id)?.name;

  const save = async () => {
    if (!draft) return;
    setSaveError(null);
    const body: CategoryPatch = {
      name: draft.name.trim(),
      sort_order: Number(draft.sort_order),
      reason: draft.reason.trim(),
      ...(workflows ? { workflow_id: draft.workflow || null } : {}),
      ...(canDefine ? { description: draft.description.trim(), is_routable: draft.is_routable } : {}),
    };
    try {
      await api.patch<CategoryOut>(`/api/categories/${draft.slug}`, body);
      forgetCategories();
      setDraft(null);
      await load();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Couldn't save the category.");
    }
  };

  const order = Number(draft?.sort_order);
  const valid =
    !!draft?.name.trim() &&
    !!draft?.reason.trim() &&
    (!canDefine || !!draft?.description.trim()) &&
    draft.sort_order !== "" &&
    Number.isInteger(order) &&
    order >= 0;

  return (
    <Page width="record" className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Admin / Settings"
        title="Categories"
        description="The categories a ticket can be given. The text beside each one is what the classifier is told it means: a manager's change to it reaches the classifier on the next ticket, with no evaluation run."
      />

      {error && <ErrorState title={error} onRetry={() => { setError(null); void load(); }} />}
      {!error && teamsFailed && <ErrorState compact title="Couldn't load the owning teams." onRetry={() => void load()} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[820px]">
          <TableHeader>
            <TableRow>
              <TableHead className="w-12">Order</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>What it covers</TableHead>
              <TableHead>Owning team</TableHead>
              <TableHead>Workflow</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStatus colSpan={6} rows={categories} error={!!error} empty={<EmptyState compact title="No categories" />} />
            {categories?.map((c) => (
              <TableRow key={c.slug} className={c.is_active ? "" : "text-muted-foreground"}>
                <TableCell className="align-top tabular-nums">{c.sort_order}</TableCell>
                <TableCell className="align-top">
                  <span className="font-medium">{c.name}</span>
                  <span className="block font-mono text-[11px] text-muted-foreground">
                    {c.slug} · v{c.version}
                  </span>
                  <span className="mt-1 flex flex-wrap gap-1">
                    {c.is_security && <Badge variant="info">security</Badge>}
                    {!c.is_routable && <Badge variant="neutral">not routed</Badge>}
                    {!c.is_active && <Badge variant="neutral">inactive</Badge>}
                  </span>
                </TableCell>
                <TableCell className="max-w-[420px] align-top text-xs leading-relaxed whitespace-normal text-muted-foreground">
                  {c.description}
                </TableCell>
                <TableCell className="align-top">
                  {teamsFailed ? (
                    <span className="text-muted-foreground">?</span>
                  ) : (
                    (owners[c.slug] ?? <span className="text-muted-foreground">—</span>)
                  )}
                </TableCell>
                <TableCell className="align-top">
                  {c.workflow_id === null ? (
                    <span className="text-muted-foreground">Default</span>
                  ) : (
                    (workflowName(c.workflow_id) ?? <span className="text-muted-foreground">?</span>)
                  )}
                </TableCell>
                <TableCell className="align-top text-right">
                  {canEdit && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setSaveError(null);
                        setDraft({
                          slug: c.slug,
                          name: c.name,
                          sort_order: String(c.sort_order),
                          description: c.description,
                          is_routable: c.is_routable,
                          workflow: c.workflow_id ?? "",
                          reason: "",
                        });
                      }}
                    >
                      Edit
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Modal
        open={!!draft}
        onClose={() => setDraft(null)}
        title={draft ? `Edit ${draft.slug}` : "Edit category"}
        subtitle={
          canDefine
            ? "The name and order are what people see; the description is what the classifier reads. Tickets keep the category's slug."
            : "The name and order are what people see; tickets keep the category's slug."
        }
        footer={
          <>
            <Button variant="outline" onClick={() => setDraft(null)}>
              Cancel
            </Button>
            <Button disabled={!valid} onClick={() => void save()}>
              Save
            </Button>
          </>
        }
      >
        {draft && (
          <div className="flex flex-col gap-3">
            <Labeled label="Name" required>
              <Input value={draft.name} maxLength={100} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </Labeled>
            <Labeled label="Order" hint="Lower comes first in every category list.">
              <Input type="number" min={0} value={draft.sort_order} onChange={(e) => setDraft({ ...draft, sort_order: e.target.value })} />
            </Labeled>
            {workflows ? (
              <Labeled
                label="Workflow"
                hint="When a ticket in this category is routed, or a reviewer hands it off, it moves into this workflow at the same status. A strict workflow needs a transition out of Auto-routed, Pending review and Escalated."
              >
                <NativeSelect value={draft.workflow} onChange={(e) => setDraft({ ...draft, workflow: e.target.value })}>
                  <option value="">Default workflow</option>
                  {workflows
                    .filter((w) => !w.is_default)
                    .map((w) => (
                      <option key={w.id} value={w.id}>
                        {w.name}
                      </option>
                    ))}
                </NativeSelect>
              </Labeled>
            ) : (
              <ErrorState compact title="Couldn't load the workflows; the category keeps its workflow." />
            )}
            {canDefine && (
              <>
                <Labeled label="What it covers" required hint="The classifier reads this on every ticket.">
                  <Textarea rows={6} value={draft.description} maxLength={2000} onChange={(e) => setDraft({ ...draft, description: e.target.value })} />
                </Labeled>
                <label className="flex items-start gap-2 text-sm">
                  <Checkbox className="mt-0.5" checked={draft.is_routable} onCheckedChange={(on) => setDraft({ ...draft, is_routable: on === true })} />
                  <span>
                    Routed automatically
                    <span className="block text-xs text-muted-foreground">Off: a ticket the AI puts in this category goes to a person to route.</span>
                  </span>
                </label>
              </>
            )}
            <Labeled label="Reason" required>
              <Textarea value={draft.reason} maxLength={500} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
            </Labeled>
            {saveError && <ErrorState compact title="The category wasn't saved">{saveError}</ErrorState>}
          </div>
        )}
      </Modal>
    </Page>
  );
}
