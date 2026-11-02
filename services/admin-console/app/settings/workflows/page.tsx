"use client";

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
    <div className="mx-auto max-w-[1080px]">
      <header className="mb-5 flex items-end justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Workflows</h1>
          <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">
            The stages a ticket moves through after triage, which moves are allowed, and what runs when they happen.
            Every workflow keeps the triage statuses; only the triage pipeline moves tickets into them.
          </p>
        </div>
        {canEdit && !creating && (
          <Button onClick={() => setCreating(true)}>
            New workflow
          </Button>
        )}
      </header>

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

      {workflows && (
        <Card className="overflow-hidden">
          <Table className="w-full text-sm">
            <TableHeader className="bg-muted text-left text-xs text-muted-foreground">
              <TableRow>
                <TableHead className="px-4 py-2.5 font-medium">Workflow</TableHead>
                <TableHead className="px-4 py-2.5 font-medium">Moves</TableHead>
                <TableHead className="px-4 py-2.5 text-right font-medium">Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {workflows.map((w) => (
                <TableRow key={w.id} className="border-t border-border hover:bg-muted">
                  <TableCell className="px-4 py-3">
                    <Link href={`/settings/workflows/${w.id}`} className="font-medium hover:text-primary">
                      {w.name}
                    </Link>
                    {w.is_default && <Badge variant="info" className="ml-2">Default for new tickets</Badge>}
                    {w.description && <p className="text-xs text-muted-foreground">{w.description}</p>}
                  </TableCell>
                  <TableCell className="px-4 py-3 text-muted-foreground">
                    {w.transition_policy === "strict" ? "Defined transitions only" : "Any to any"}
                  </TableCell>
                  <TableCell className="px-4 py-3 text-right text-muted-foreground">{relativeTime(w.updated_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}
