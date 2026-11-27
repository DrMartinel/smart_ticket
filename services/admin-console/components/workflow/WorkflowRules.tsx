"use client";

// "Which workflow": the ordered rules that choose a ticket's workflow at handoff, and a preview of
// what they choose (ADR-0055).

import { ArrowDown, ArrowUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import Modal, { Labeled } from "@/components/Modal";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { NativeSelect } from "@/components/ui/native-select";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api } from "@/lib/api";
import { useCategories } from "@/lib/categories";
import { BRANCH_LABEL } from "@/lib/explain";
import { relativeTime } from "@/lib/format";
import type { Workflow } from "@/lib/lifecycle";
import type {
  Branch,
  Priority,
  WorkflowRuleDeleteIn,
  WorkflowRuleIn,
  WorkflowRuleOut,
  WorkflowRulePatch,
  WorkflowRulePreviewOut,
  WorkflowRuleReorderIn,
} from "@/lib/types/generated";

const URL = "/api/lifecycle/workflow-rules";
// The branches whose tickets are handed off; an auto-replied ticket never is.
const BRANCHES: Branch[] = ["auto_route", "hitl", "escalate", "clarify", "block"];
const PRIORITIES: Priority[] = ["P1", "P2", "P3", "P4"];

interface Draft {
  id: string | null;
  category: string;
  branch: string;
  priority: string;
  workflow_id: string;
  is_active: boolean;
  reason: string;
}

interface Keys {
  category: string;
  branch: string;
  priority: string;
}

function failure(err: unknown, fallback: string): string {
  if (!(err instanceof ApiError)) return fallback;
  const statuses = (err.details as { statuses?: string[] } | null)?.statuses;
  return statuses ? `${err.message}: ${statuses.join(", ")}` : err.message;
}

function KeyChips({ rule }: { rule: WorkflowRuleOut }) {
  const keys = [
    rule.category && `category ${rule.category}`,
    rule.branch && (BRANCH_LABEL[rule.branch] ?? rule.branch).toLowerCase(),
    rule.priority,
  ].filter(Boolean) as string[];
  if (keys.length === 0) return <span className="text-muted-foreground">Every ticket</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {keys.map((k) => (
        <Badge key={k} variant="neutral">
          {k}
        </Badge>
      ))}
    </span>
  );
}

function KeyPickers({
  keys,
  onChange,
  categories,
}: {
  keys: Keys;
  onChange: (keys: Keys) => void;
  categories: { slug: string; name: string }[];
}) {
  return (
    <>
      <Labeled label="Category">
        <NativeSelect value={keys.category} onChange={(e) => onChange({ ...keys, category: e.target.value })}>
          <option value="">Any category</option>
          {categories.map((c) => (
            <option key={c.slug} value={c.slug}>
              {c.name}
            </option>
          ))}
        </NativeSelect>
      </Labeled>
      <Labeled label="How it was handed off">
        <NativeSelect value={keys.branch} onChange={(e) => onChange({ ...keys, branch: e.target.value })}>
          <option value="">Any way</option>
          {BRANCHES.map((b) => (
            <option key={b} value={b}>
              {BRANCH_LABEL[b] ?? b}
            </option>
          ))}
        </NativeSelect>
      </Labeled>
      <Labeled label="Priority">
        <NativeSelect value={keys.priority} onChange={(e) => onChange({ ...keys, priority: e.target.value })}>
          <option value="">Any priority</option>
          {PRIORITIES.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </NativeSelect>
      </Labeled>
    </>
  );
}

export default function WorkflowRules({ workflows, canEdit }: { workflows: Workflow[]; canEdit: boolean }) {
  const { categories } = useCategories();
  const [rules, setRules] = useState<WorkflowRuleOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [deleting, setDeleting] = useState<{ rule: WorkflowRuleOut; reason: string } | null>(null);
  const [order, setOrder] = useState<WorkflowRuleOut[] | null>(null);
  const [orderReason, setOrderReason] = useState("");
  const [saveError, setSaveError] = useState<string | null>(null);
  const [probe, setProbe] = useState<Keys>({ category: "", branch: "", priority: "" });
  const [withInactive, setWithInactive] = useState(false);
  const [preview, setPreview] = useState<WorkflowRulePreviewOut | null>(null);
  const [previewError, setPreviewError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setRules(await api.get<WorkflowRuleOut[]>(URL));
      setError(null);
    } catch {
      setError("Couldn't load the workflow rules.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const runPreview = useCallback(async () => {
    const query = new URLSearchParams();
    if (probe.category) query.set("category", probe.category);
    if (probe.branch) query.set("branch", probe.branch);
    if (probe.priority) query.set("priority", probe.priority);
    if (withInactive) query.set("include_inactive", "true");
    try {
      setPreview(await api.get<WorkflowRulePreviewOut>(`${URL}/preview?${query}`));
      setPreviewError(null);
    } catch (err) {
      setPreviewError(failure(err, "Couldn't run the preview."));
    }
  }, [probe, withInactive]);

  useEffect(() => {
    void runPreview();
  }, [runPreview, rules]);

  const save = async () => {
    if (!draft) return;
    setSaveError(null);
    const keys = {
      category: draft.category || null,
      branch: (draft.branch || null) as Branch | null,
      priority: (draft.priority || null) as Priority | null,
      workflow_id: draft.workflow_id,
      is_active: draft.is_active,
      reason: draft.reason.trim(),
    };
    try {
      if (draft.id) await api.patch<WorkflowRuleOut>(`${URL}/${draft.id}`, keys satisfies WorkflowRulePatch);
      else await api.post<WorkflowRuleOut>(URL, keys satisfies WorkflowRuleIn);
      setDraft(null);
      await load();
    } catch (err) {
      setSaveError(failure(err, "Couldn't save the rule."));
    }
  };

  const remove = async () => {
    if (!deleting) return;
    setSaveError(null);
    try {
      await api.delete(`${URL}/${deleting.rule.id}`, { reason: deleting.reason.trim() } satisfies WorkflowRuleDeleteIn);
      setDeleting(null);
      await load();
    } catch (err) {
      setSaveError(failure(err, "Couldn't delete the rule."));
    }
  };

  const saveOrder = async () => {
    if (!order) return;
    setSaveError(null);
    try {
      const body: WorkflowRuleReorderIn = { ids: order.map((r) => r.id), reason: orderReason.trim() };
      setRules(await api.post<WorkflowRuleOut[]>(`${URL}/reorder`, body));
      setOrder(null);
      setOrderReason("");
    } catch (err) {
      setSaveError(failure(err, "Couldn't save the order."));
    }
  };

  const move = (index: number, by: -1 | 1) => {
    if (!order) return;
    const next = [...order];
    [next[index], next[index + by]] = [next[index + by], next[index]];
    setOrder(next);
  };

  const shown = order ?? rules;
  const position = (id: string | null) => (rules ?? []).findIndex((r) => r.id === id) + 1;
  const previewSource = preview
    ? preview.rule_id
      ? `rule ${position(preview.rule_id)}`
      : preview.selected_by === "category"
        ? "the category's workflow"
        : "the default workflow"
    : null;

  return (
    <section className="flex flex-col gap-3">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold">Which workflow</h2>
          <p className="max-w-3xl text-sm text-muted-foreground">
            When a ticket is handed to people, the first active rule that matches its category, how it was handed off and its
            priority chooses its workflow. No match: the category&apos;s workflow, else the default. A ticket already in a
            workflow is never moved by a later change.
          </p>
        </div>
        {canEdit && !order && (
          <div className="flex gap-2">
            {rules && rules.length > 1 && (
              <Button variant="outline" onClick={() => setOrder(rules)}>
                Reorder
              </Button>
            )}
            <Button
              onClick={() => {
                setSaveError(null);
                setDraft({ id: null, category: "", branch: "", priority: "", workflow_id: "", is_active: true, reason: "" });
              }}
            >
              New rule
            </Button>
          </div>
        )}
      </div>

      {error && <ErrorState title={error} onRetry={() => void load()} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[640px]">
          <TableHeader>
            <TableRow>
              <TableHead className="w-12">#</TableHead>
              <TableHead>When a ticket is</TableHead>
              <TableHead>It enters</TableHead>
              <TableHead>Last change</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStatus
              colSpan={5}
              rows={shown}
              error={!!error}
              empty={<EmptyState compact title="No rules: every ticket enters its category's workflow" />}
            />
            {shown?.map((rule, i) => (
              <TableRow key={rule.id} className={rule.is_active ? "" : "text-muted-foreground"}>
                <TableCell className="align-top tabular-nums">{i + 1}</TableCell>
                <TableCell className="align-top">
                  <KeyChips rule={rule} />
                  {!rule.is_active && (
                    <Badge variant="neutral" className="mt-1">
                      inactive
                    </Badge>
                  )}
                </TableCell>
                <TableCell className="align-top font-medium">{rule.workflow_name}</TableCell>
                <TableCell className="max-w-[260px] align-top text-xs whitespace-normal text-muted-foreground">
                  {rule.changed_by ?? "someone"}, {relativeTime(rule.updated_at)}: {rule.change_reason}
                </TableCell>
                <TableCell className="align-top text-right whitespace-nowrap">
                  {order ? (
                    <span className="inline-flex gap-1">
                      <Button variant="outline" size="sm" aria-label="Move up" disabled={i === 0} onClick={() => move(i, -1)}>
                        <ArrowUp className="size-4" />
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        aria-label="Move down"
                        disabled={i === order.length - 1}
                        onClick={() => move(i, 1)}
                      >
                        <ArrowDown className="size-4" />
                      </Button>
                    </span>
                  ) : (
                    canEdit && (
                      <span className="inline-flex gap-1">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            setSaveError(null);
                            setDraft({
                              id: rule.id,
                              category: rule.category ?? "",
                              branch: rule.branch ?? "",
                              priority: rule.priority ?? "",
                              workflow_id: rule.workflow_id,
                              is_active: rule.is_active,
                              reason: "",
                            });
                          }}
                        >
                          Edit
                        </Button>
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => {
                            setSaveError(null);
                            setDeleting({ rule, reason: "" });
                          }}
                        >
                          Delete
                        </Button>
                      </span>
                    )
                  )}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {order && (
        <Card className="flex flex-wrap items-end gap-3 p-4">
          <Labeled label="Why the order changes" required className="min-w-72 flex-1">
            <Textarea rows={2} value={orderReason} maxLength={500} onChange={(e) => setOrderReason(e.target.value)} />
          </Labeled>
          <Button disabled={!orderReason.trim()} onClick={() => void saveOrder()}>
            Save order
          </Button>
          <Button
            variant="outline"
            onClick={() => {
              setOrder(null);
              setOrderReason("");
              setSaveError(null);
            }}
          >
            Cancel
          </Button>
          {saveError && (
            <ErrorState compact title="The order wasn't saved" className="w-full">
              {saveError}
            </ErrorState>
          )}
        </Card>
      )}

      <Card className="flex flex-col gap-3 p-4">
        <div>
          <h3 className="text-sm font-semibold">Preview</h3>
          <p className="text-xs text-muted-foreground">Which workflow a ticket handed off now would enter.</p>
        </div>
        <div className="grid gap-3 sm:grid-cols-3">
          <KeyPickers keys={probe} onChange={setProbe} categories={categories} />
        </div>
        <label className="flex items-center gap-2 text-sm">
          <Checkbox checked={withInactive} onCheckedChange={(on) => setWithInactive(on === true)} />
          Count inactive rules as if they were on
        </label>
        {previewError && <ErrorState compact title={previewError} />}
        {preview && (
          <p className="text-sm" aria-live="polite">
            It would enter <span className="font-semibold">{preview.workflow_name}</span>, chosen by {previewSource}.
          </p>
        )}
      </Card>

      <Modal
        open={!!draft}
        onClose={() => setDraft(null)}
        title={draft?.id ? `Edit rule ${position(draft.id)}` : "New rule"}
        subtitle="A key left as any matches every ticket. A new rule goes last; reorder to put it first."
        footer={
          <>
            <Button variant="outline" onClick={() => setDraft(null)}>
              Cancel
            </Button>
            <Button disabled={!draft?.workflow_id || !draft.reason.trim()} onClick={() => void save()}>
              Save
            </Button>
          </>
        }
      >
        {draft && (
          <div className="flex flex-col gap-3">
            <KeyPickers
              keys={draft}
              onChange={(keys) => setDraft({ ...draft, ...keys })}
              categories={
                draft.category && !categories.some((c) => c.slug === draft.category)
                  ? [...categories, { slug: draft.category, name: `${draft.category} (inactive)` }]
                  : categories
              }
            />
            <Labeled
              label="Workflow"
              required
              hint="A strict workflow needs a transition out of Auto-routed, Pending review, Escalated and Reopened. The default workflow keeps matching tickets out of their category's."
            >
              <NativeSelect value={draft.workflow_id} onChange={(e) => setDraft({ ...draft, workflow_id: e.target.value })}>
                <option value="" disabled>
                  Choose a workflow
                </option>
                {workflows.map((w) => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                    {w.is_default && w.name.toLowerCase() !== "default" ? " (default)" : ""}
                  </option>
                ))}
              </NativeSelect>
            </Labeled>
            <label className="flex items-start gap-2 text-sm">
              <Checkbox className="mt-0.5" checked={draft.is_active} onCheckedChange={(on) => setDraft({ ...draft, is_active: on === true })} />
              <span>
                Active
                <span className="block text-xs text-muted-foreground">Off: the rule is skipped; the preview can still count it.</span>
              </span>
            </label>
            <Labeled label="Reason" required>
              <Textarea value={draft.reason} maxLength={500} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
            </Labeled>
            {saveError && <ErrorState compact title="The rule wasn't saved">{saveError}</ErrorState>}
          </div>
        )}
      </Modal>

      <Modal
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title={deleting ? `Delete rule ${position(deleting.rule.id)}` : "Delete rule"}
        subtitle="Tickets already in its workflow stay there."
        size="md"
        footer={
          <>
            <Button variant="outline" onClick={() => setDeleting(null)}>
              Cancel
            </Button>
            <Button variant="destructive" disabled={!deleting?.reason.trim()} onClick={() => void remove()}>
              Delete
            </Button>
          </>
        }
      >
        {deleting && (
          <div className="flex flex-col gap-3">
            <Labeled label="Reason" required>
              <Textarea value={deleting.reason} maxLength={500} onChange={(e) => setDeleting({ ...deleting, reason: e.target.value })} />
            </Labeled>
            {saveError && <ErrorState compact title="The rule wasn't deleted">{saveError}</ErrorState>}
          </div>
        )}
      </Modal>
    </section>
  );
}
