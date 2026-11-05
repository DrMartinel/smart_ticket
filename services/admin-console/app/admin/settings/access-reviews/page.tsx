"use client";

// Access reviews (F14, UC-F14-07): a campaign over a set of grants, each answered by its reviewer, closed with a rule for the unanswered.

import { useCallback, useEffect, useState } from "react";
import Modal, { Labeled } from "@/components/Modal";
import { SectionTabs } from "@/components/TabNav";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Page, PageHeader } from "@/components/ui/page-header";
import { Card } from "@/components/ui/card";
import { ErrorState, TableStatus } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import { UNGRANTABLE_ROLES } from "@/lib/permissions";
import type { AccountOut, CampaignDetailOut, CampaignOut, DepartmentOut, RoleOut } from "@/lib/types/generated";

interface Draft {
  name: string;
  role: string;
  department: string;
  fallback_reviewer: string;
  on_no_answer: "flag" | "revoke";
  closes_at: string;
}

export default function AccessReviewsPage() {
  const user = useRequireAuth();
  const toast = useToast();
  const [campaigns, setCampaigns] = useState<CampaignOut[] | null>(null);
  const [roles, setRoles] = useState<RoleOut[]>([]);
  const [departments, setDepartments] = useState<DepartmentOut[]>([]);
  const [people, setPeople] = useState<AccountOut[]>([]);
  const [detail, setDetail] = useState<CampaignDetailOut | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [closing, setClosing] = useState<CampaignOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [formError, setFormError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setCampaigns(await api.get<CampaignOut[]>("/api/access/reviews"));
      setError(null);
    } catch {
      setError("Couldn't load the access reviews.");
    }
  }, []);

  useEffect(() => {
    if (!user) return;
    void load();
    void Promise.all([
      api.get<RoleOut[]>("/api/access/roles").catch(() => []),
      api.get<DepartmentOut[]>("/api/org/departments").catch(() => []),
      api.get<AccountOut[]>("/api/accounts/people").catch(() => []),
    ]).then(([r, d, p]) => {
      setRoles(r);
      setDepartments(d);
      setPeople(p.filter((x) => x.is_active && x.role !== "employee"));
    });
  }, [user, load]);

  if (!user) return null;

  const openDetail = async (id: string) => {
    try {
      setDetail(await api.get<CampaignDetailOut>(`/api/access/reviews/${id}`));
    } catch {
      toast.error("Couldn't load the review.");
    }
  };

  const create = async () => {
    if (!draft) return;
    setFormError(null);
    try {
      const created = await api.post<CampaignOut>("/api/access/reviews", {
        name: draft.name,
        role: draft.role || null,
        department: draft.department || null,
        fallback_reviewer: draft.fallback_reviewer,
        on_no_answer: draft.on_no_answer,
        closes_at: draft.closes_at ? new Date(`${draft.closes_at}T23:59:59`).toISOString() : null,
      });
      toast.success(`Opened ${created.name}: ${created.total} grant(s) sent to their reviewers`);
      setDraft(null);
      await load();
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : "Couldn't open the review.");
    }
  };

  const close = async () => {
    if (!closing) return;
    try {
      await api.post(`/api/access/reviews/${closing.id}/close`, {});
      toast.success(`Closed ${closing.name}`);
      setDetail(null);
      await load();
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't close the review.");
      throw err;
    }
  };

  return (
    <Page width="record" className="flex flex-col gap-4">
      <SectionTabs className="mb-1" />
      <PageHeader
        className="mb-2"
        eyebrow="Admin / People & access"
        title="Access reviews"
        description="Each grant goes to the person's line manager, else their department head, else the fallback reviewer; nobody reviews their own. Structural grants (team leads, department heads) follow the structure and aren't reviewed."
        actions={
          <Button
            onClick={() => {
              setFormError(null);
              setDraft({ name: "", role: "", department: "", fallback_reviewer: user.username, on_no_answer: "flag", closes_at: "" });
            }}
          >
            Open a review
          </Button>
        }
      />

      {error && <ErrorState title={error} onRetry={() => void load()} />}

      <Card className="overflow-x-auto">
        <Table className="min-w-[760px]">
          <TableHeader>
            <TableRow>
              <TableHead>Review</TableHead>
              <TableHead>Covers</TableHead>
              <TableHead>Progress</TableHead>
              <TableHead>Closes</TableHead>
              <TableHead>Unanswered</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStatus colSpan={5} rows={campaigns} error={!!error} empty="No access reviews yet" />
            {(campaigns ?? []).map((c) => (
              <TableRow key={c.id} className="cursor-pointer hover:bg-muted/50" onClick={() => void openDetail(c.id)}>
                <TableCell>
                  <span className="font-medium text-primary">{c.name}</span>
                  <Badge variant={c.state === "open" ? "info" : "neutral"} className="ml-2">
                    {c.state}
                  </Badge>
                  <span className="block text-xs text-muted-foreground">by {c.created_by}</span>
                </TableCell>
                <TableCell className="text-sm">
                  {[c.role ? roles.find((r) => r.urn === c.role)?.name ?? c.role : "All roles", c.department ?? "all departments"].join(" · ")}
                </TableCell>
                <TableCell className="text-sm tabular-nums">
                  {c.total - c.pending}/{c.total} answered
                  <span className="block text-xs text-muted-foreground">
                    {c.kept} kept · {c.revoked} revoked
                  </span>
                </TableCell>
                <TableCell>{formatDate(c.closed_at ?? c.closes_at)}</TableCell>
                <TableCell className="capitalize">{c.on_no_answer}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      <Modal
        open={!!detail}
        onClose={() => setDetail(null)}
        title={detail?.name ?? ""}
        subtitle={detail ? `${detail.state} · closes ${formatDate(detail.closes_at)} · unanswered grants are ${detail.on_no_answer === "revoke" ? "revoked" : "flagged"}` : undefined}
        width="max-w-3xl"
        footer={
          detail?.state === "open" ? (
            <Button variant="outline" onClick={() => setClosing(detail)}>
              Close now
            </Button>
          ) : undefined
        }
      >
        {detail && (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Person</TableHead>
                <TableHead>Grant</TableHead>
                <TableHead>Reviewer</TableHead>
                <TableHead>Answer</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {(detail.items ?? []).map((i) => (
                <TableRow key={i.id}>
                  <TableCell>
                    {i.user}
                    <span className="block text-xs text-muted-foreground">{i.user_name}</span>
                  </TableCell>
                  <TableCell>
                    {i.role_name}
                    <span className="block text-xs text-muted-foreground">{i.scope}</span>
                  </TableCell>
                  <TableCell>{i.reviewer}</TableCell>
                  <TableCell>
                    {i.decision ? (
                      <Badge variant={i.decision === "keep" ? "ok" : "danger"}>{i.decision}</Badge>
                    ) : (
                      <span className="text-muted-foreground">waiting</span>
                    )}
                    {i.note && <span className="block text-xs text-muted-foreground">{i.note}</span>}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Modal>

      <Modal
        open={!!draft}
        onClose={() => setDraft(null)}
        title="Open an access review"
        footer={
          draft && (
            <Button disabled={!draft.name.trim() || !draft.fallback_reviewer} onClick={() => void create()}>
              Open review
            </Button>
          )
        }
      >
        {draft && (
          <div className="grid gap-3 text-sm sm:grid-cols-2">
            <Labeled label="Name" required className="sm:col-span-2">
              <Input value={draft.name} placeholder="Q4 editors" onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </Labeled>
            <Labeled label="Role" hint="Empty for every manual grant.">
              <NativeSelect value={draft.role} onChange={(e) => setDraft({ ...draft, role: e.target.value })}>
                <option value="">All roles</option>
                {roles.filter((r) => !UNGRANTABLE_ROLES.has(r.urn)).map((r) => (
                  <option key={r.urn} value={r.urn}>
                    {r.name}
                  </option>
                ))}
              </NativeSelect>
            </Labeled>
            <Labeled label="Department" hint="People in it and below.">
              <NativeSelect value={draft.department} onChange={(e) => setDraft({ ...draft, department: e.target.value })}>
                <option value="">All departments</option>
                {departments.map((d) => (
                  <option key={d.code} value={d.code}>
                    {d.name} ({d.code})
                  </option>
                ))}
              </NativeSelect>
            </Labeled>
            <Labeled label="Fallback reviewer" required hint="Answers grants nobody else can.">
              <NativeSelect value={draft.fallback_reviewer} onChange={(e) => setDraft({ ...draft, fallback_reviewer: e.target.value })}>
                {people.map((p) => (
                  <option key={p.username} value={p.username}>
                    {p.username}
                  </option>
                ))}
              </NativeSelect>
            </Labeled>
            <Labeled label="Unanswered at close">
              <NativeSelect value={draft.on_no_answer} onChange={(e) => setDraft({ ...draft, on_no_answer: e.target.value as Draft["on_no_answer"] })}>
                <option value="flag">Flag for review</option>
                <option value="revoke">Revoke</option>
              </NativeSelect>
            </Labeled>
            <Labeled label="Closes" hint="Empty for the default period.">
              <Input type="date" value={draft.closes_at} onChange={(e) => setDraft({ ...draft, closes_at: e.target.value })} />
            </Labeled>
            {formError && <ErrorState compact title={formError} className="sm:col-span-2" />}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={!!closing}
        title={closing ? `Close ${closing.name}?` : ""}
        confirmLabel={closing?.on_no_answer === "revoke" ? "Close and revoke unanswered grants" : "Close and flag unanswered grants"}
        destructive={closing?.on_no_answer === "revoke"}
        onConfirm={close}
        onClose={() => setClosing(null)}
      >
        <p className="text-sm text-muted-foreground">{closing?.pending ?? 0} grant(s) have no answer yet.</p>
      </ConfirmDialog>
    </Page>
  );
}
