"use client";

// Thresholds (F9 · Threshold history 16-1436): the loaded file and its approval, every change
// request, and a new one: the whole file, validated with the boot model (BR-F9-05).

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { ChangeRequestDetailOut, ChangeRequestOut, CurrentThresholdsOut } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge, type Tone } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";

const STATE_TONE: Record<string, Tone> = {
  draft: "neutral",
  pending: "warn",
  approved: "ok",
  loaded: "ok",
  rejected: "danger",
};

export default function ThresholdsPage() {
  const user = useRequireAuth();
  const router = useRouter();
  const [current, setCurrent] = useState<CurrentThresholdsOut | null>(null);
  const [history, setHistory] = useState<ChangeRequestOut[]>([]);
  const [text, setText] = useState("");
  const [evidence, setEvidence] = useState("");
  const [composing, setComposing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [c, h] = await Promise.all([
      api.get<CurrentThresholdsOut>("/api/thresholds/current"),
      api.get<ChangeRequestOut[]>("/api/thresholds/history"),
    ]);
    setCurrent(c);
    setHistory(h);
  }, []);

  useEffect(() => {
    if (user) load().catch(() => setError("Couldn't load the thresholds."));
  }, [user, load]);

  if (!user) return null;

  const mayPropose = user.role === "manager" || user.role === "technician" || (user.capabilities ?? []).includes("workflow_admin");

  const startDraft = () => {
    if (!current) return;
    setText(current.yaml.replace(/^version: .*$/m, `version: "${current.next_version}"`));
    setComposing(true);
  };

  const create = async () => {
    setError(null);
    try {
      const made = await api.post<ChangeRequestDetailOut>("/api/thresholds/change-requests", { yaml_text: text, evidence });
      router.push(`/settings/thresholds/${made.id}`);
    } catch (err) {
      if (err instanceof ApiError) {
        const path = (err.details as { path?: string } | null)?.path;
        setError(`${err.code}: ${err.message}${path ? ` (at ${path})` : ""}`);
      } else setError("Couldn't create the request.");
    }
  };

  return (
    <div className="mx-auto flex max-w-[1080px] flex-col gap-4">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Thresholds</h1>
          <p className="text-xs text-muted-foreground">
            thresholds.yaml is the only home of tunables. A change is the whole file, approved by two people who aren&apos;t its author,
            then shipped by PR under its request id (ADR-0035).
          </p>
        </div>
        {mayPropose && !composing && (
          <Button onClick={startDraft} disabled={!current}>
            New change request
          </Button>
        )}
      </header>

      {current && (
        <Card asChild>
          <section className={`p-4 text-sm ${current.approved ? "" : "border-danger"}`}>
            <p className="text-[11px] uppercase tracking-wider text-muted-foreground">Loaded file</p>
            <p className="mt-1 text-lg font-semibold">{current.change_request ?? current.version}</p>
            <p className="text-xs text-muted-foreground">
              {current.approved ? "approved" : "NOT approved: every branch is in shadow"}
              {!current.checked && " · approval check off (THRESHOLDS_REQUIRE_APPROVAL=false)"} · sha256 {current.sha256.slice(0, 12)}…
              {current.loaded_at && ` · loaded ${new Date(current.loaded_at).toLocaleString()}`}
            </p>
          </section>
        </Card>
      )}

      {composing && (
        <Card asChild>
          <section className="flex flex-col gap-3 p-4 text-sm">
            <p className="text-xs text-muted-foreground">
              The file must keep <code>version: &quot;{current?.next_version}&quot;</code>: that is this request&apos;s id, and the text that
              ships must be the text that was approved.
            </p>
            <Textarea className="min-h-[360px] font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
            <Input value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="Evidence: calibration run id, evals/HISTORY.md entry" />
            {error && <p className="text-danger">{error}</p>}
            <div className="flex gap-2">
              <Button onClick={() => void create()}>
                Validate and save draft
              </Button>
              <Button variant="outline" onClick={() => setComposing(false)}>
                Cancel
              </Button>
            </div>
          </section>
        </Card>
      )}

      <Card asChild>
        <section className="overflow-x-auto">
          <Table className="w-full min-w-[720px] text-left text-sm">
            <TableHeader className="text-[11px] uppercase tracking-wider text-muted-foreground">
              <TableRow>
                <TableHead className="px-4 py-2.5 font-medium">Version</TableHead>
                <TableHead className="px-4 py-2.5 font-medium">State</TableHead>
                <TableHead className="px-4 py-2.5 font-medium">Author</TableHead>
                <TableHead className="px-4 py-2.5 font-medium">Approvals</TableHead>
                <TableHead className="px-4 py-2.5 font-medium">Created</TableHead>
                <TableHead className="px-4 py-2.5 font-medium">Loaded</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {history.map((r) => (
                <TableRow key={r.id} className="border-t border-border">
                  <TableCell className="px-4 py-2.5">
                    <Link href={`/settings/thresholds/${r.id}`} className="font-mono text-primary hover:underline">
                      {r.version}
                    </Link>
                  </TableCell>
                  <TableCell className="px-4 py-2.5">
                    <Badge variant={STATE_TONE[r.state] ?? "neutral"}>{r.state}</Badge>
                  </TableCell>
                  <TableCell className="px-4 py-2.5">{r.author ?? "migration"}</TableCell>
                  <TableCell className="px-4 py-2.5">{r.approvals.map((a) => String(a.user)).join(", ") || "—"}</TableCell>
                  <TableCell className="px-4 py-2.5">{new Date(r.created_at).toLocaleDateString()}</TableCell>
                  <TableCell className="px-4 py-2.5">{r.loaded_at ? new Date(r.loaded_at).toLocaleString() : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      </Card>
    </div>
  );
}
