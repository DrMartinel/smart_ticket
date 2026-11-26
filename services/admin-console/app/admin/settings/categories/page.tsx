"use client";

// Ticket categories (ADR-0049): each category, what it means, the team that owns it; rename and reorder.

import { useCallback, useEffect, useState } from "react";
import Modal, { Labeled } from "@/components/Modal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { forgetCategories } from "@/lib/categories";
import { P, can } from "@/lib/permissions";
import type { CategoryOut, CategoryPatch, TeamOut } from "@/lib/types/generated";

interface Draft {
  slug: string;
  name: string;
  sort_order: string;
  reason: string;
}

export default function CategoriesPage() {
  const user = useRequireAuth();
  const [categories, setCategories] = useState<CategoryOut[] | null>(null);
  const [owners, setOwners] = useState<Record<string, string>>({});
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [all, teams] = await Promise.all([
        api.get<CategoryOut[]>("/api/categories"),
        api.get<TeamOut[]>("/api/teams").catch(() => [] as TeamOut[]),
      ]);
      setCategories(all);
      setOwners(Object.fromEntries(teams.filter((t) => t.is_active).flatMap((t) => t.categories.map((c) => [c, t.name]))));
    } catch {
      setError("Couldn't load the categories.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;
  const canEdit = can(user, P.categoriesManage);

  const save = async () => {
    if (!draft) return;
    setSaveError(null);
    const body: CategoryPatch = { name: draft.name, sort_order: Number(draft.sort_order), reason: draft.reason };
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
  const valid = !!draft?.name.trim() && !!draft?.reason.trim() && draft.sort_order !== "" && Number.isInteger(order) && order >= 0;

  return (
    <Page width="record" className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Admin / Settings"
        title="Categories"
        description="The categories a ticket can be given. The text under each one is what the classifier is told it means; it changes by pull request for now."
      />

      {error && <ErrorState title={error} onRetry={() => { setError(null); void load(); }} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[820px]">
          <TableHeader>
            <TableRow>
              <TableHead className="w-12">Order</TableHead>
              <TableHead>Category</TableHead>
              <TableHead>What it covers</TableHead>
              <TableHead>Owning team</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStatus colSpan={5} rows={categories} error={!!error} empty={<EmptyState compact title="No categories" />} />
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
                <TableCell className="align-top">{owners[c.slug] ?? <span className="text-muted-foreground">—</span>}</TableCell>
                <TableCell className="align-top text-right">
                  {canEdit && (
                    <Button
                      variant="outline"
                      size="sm"
                      onClick={() => {
                        setSaveError(null);
                        setDraft({ slug: c.slug, name: c.name, sort_order: String(c.sort_order), reason: "" });
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
        subtitle="The name and order are what people see; tickets keep the category's slug."
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
