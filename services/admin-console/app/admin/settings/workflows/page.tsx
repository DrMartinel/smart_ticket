"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, LoadingState, TableStatus } from "@/components/ui/states";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { relativeTime } from "@/lib/format";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";

interface Workflow {
  id: string;
  name: string;
  description: string;
  transition_policy: "strict" | "open";
  is_default: boolean;
  updated_at: string;
}

export default function WorkflowsPage() {
  const user = useRequireAuth();
  const [workflows, setWorkflows] = useState<Workflow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [policy, setPolicy] = useState<"strict" | "open">("strict");

  const load = () =>
    api
      .get<Workflow[]>("/api/lifecycle/workflows")
      .then(setWorkflows)
      .catch(() => setError("Couldn't load workflows."));

  useEffect(() => {
    if (user) void load();
  }, [user]);

  if (!user) return null;
  const canEdit = user.role === "manager";

  const create = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    try {
      await api.post("/api/lifecycle/workflows", { name: name.trim(), transition_policy: policy });
      setName("");
      setCreating(false);
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't create the workflow.");
    }
  };

  return (
    <Page className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Admin / Settings"
        title="Workflows"
        description={<>The stages a ticket moves through after triage, which moves are allowed, and what runs when they happen.
            Every workflow keeps the triage statuses; only the triage pipeline moves tickets into them.</>}
        actions={
      <>
      {canEdit && !creating && (
        <Button onClick={() => setCreating(true)}>
          New workflow
        </Button>
      )}
      </>
      }
      />

      {error && <Alert variant="danger" className="mb-4 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}

      {creating && (
        <Card asChild>
          <form onSubmit={create} className="mb-5 flex flex-wrap items-end gap-3 p-4">
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted-foreground">Name</span>
              <Input className="w-64" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
            </label>
            <label className="flex flex-col gap-1 text-sm">
              <span className="text-xs text-muted-foreground">Moves</span>
              <NativeSelect wrapperClassName="w-72" value={policy} onChange={(e) => setPolicy(e.target.value as "strict" | "open")}>
                <option value="strict">Only the transitions you define</option>
                <option value="open">Any status to any status</option>
              </NativeSelect>
            </label>
            <Button type="submit">
              Create
            </Button>
            <Button variant="outline" type="button" onClick={() => setCreating(false)}>
              Cancel
            </Button>
          </form>
        </Card>
      )}

      {workflows === null && !error && <LoadingState rows={3} label="Loading workflows" />}
      {workflows && (
        <Card className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Workflow</TableHead>
                <TableHead>Moves</TableHead>
                <TableHead className="text-right">Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workflows.map((w) => (
                <TableRow key={w.id} className="hover:bg-muted">
                  <TableCell className="py-3">
                    <Link href={`/admin/settings/workflows/${w.id}`} className="font-medium hover:text-primary">
                      {w.name}
                    </Link>
                    {w.is_default && <Badge variant="info" className="ml-2">Default for new tickets</Badge>}
                    {w.description && <p className="text-xs text-muted-foreground">{w.description}</p>}
                  </TableCell>
                  <TableCell className="py-3 text-muted-foreground">
                    {w.transition_policy === "strict" ? "Defined transitions only" : "Any to any"}
                  </TableCell>
                  <TableCell className="py-3 text-right text-muted-foreground">{relativeTime(w.updated_at)}</TableCell>
                </TableRow>
              ))}
              <TableStatus colSpan={3} rows={workflows} empty={<EmptyState compact title="No workflows yet" />} />
            </TableBody>
          </Table>
        </Card>
      )}
    </Page>
  );
}
