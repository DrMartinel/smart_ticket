"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { relativeTime } from "@/lib/format";

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
          <p className="mt-0.5 max-w-2xl text-sm text-[var(--text-muted)]">
            The stages a ticket moves through after triage, which moves are allowed, and what runs when they happen.
            Every workflow keeps the triage statuses; only the triage pipeline moves tickets into them.
          </p>
        </div>
        {canEdit && !creating && (
          <button className="btn btn-primary" onClick={() => setCreating(true)}>
            New workflow
          </button>
        )}
      </header>

      {error && <p className="tone-danger mb-4 rounded-[5px] px-3 py-2 text-sm">{error}</p>}

      {creating && (
        <form onSubmit={create} className="card mb-5 flex flex-wrap items-end gap-3 p-4">
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-[var(--text-muted)]">Name</span>
            <input className="field w-64" value={name} onChange={(e) => setName(e.target.value)} autoFocus required />
          </label>
          <label className="flex flex-col gap-1 text-sm">
            <span className="text-xs text-[var(--text-muted)]">Moves</span>
            <select className="field w-72" value={policy} onChange={(e) => setPolicy(e.target.value as "strict" | "open")}>
              <option value="strict">Only the transitions you define</option>
              <option value="open">Any status to any status</option>
            </select>
          </label>
          <button type="submit" className="btn btn-primary">
            Create
          </button>
          <button type="button" className="btn btn-secondary" onClick={() => setCreating(false)}>
            Cancel
          </button>
        </form>
      )}

      {workflows && (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-[var(--surface-2)] text-left text-xs text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-2.5 font-medium">Workflow</th>
                <th className="px-4 py-2.5 font-medium">Moves</th>
                <th className="px-4 py-2.5 text-right font-medium">Updated</th>
              </tr>
            </thead>
            <tbody>
              {workflows.map((w) => (
                <tr key={w.id} className="border-t border-[var(--border)] hover:bg-[var(--surface-2)]">
                  <td className="px-4 py-3">
                    <Link href={`/settings/workflows/${w.id}`} className="font-medium hover:text-[var(--accent)]">
                      {w.name}
                    </Link>
                    {w.is_default && <span className="badge tone-info ml-2">Default for new tickets</span>}
                    {w.description && <p className="text-xs text-[var(--text-muted)]">{w.description}</p>}
                  </td>
                  <td className="px-4 py-3 text-[var(--text-muted)]">
                    {w.transition_policy === "strict" ? "Defined transitions only" : "Any to any"}
                  </td>
                  <td className="px-4 py-3 text-right text-[var(--text-muted)]">{relativeTime(w.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
