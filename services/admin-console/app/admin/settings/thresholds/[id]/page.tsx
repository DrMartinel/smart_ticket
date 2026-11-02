"use client";

// One threshold change request (F9 · Threshold change request 16-1336): the diff against the loaded
// file, the evidence, and the approvals; two, neither by the author, one a manager's.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { ChangeRequestDetailOut } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Input } from "@/components/ui/input";

export default function ChangeRequestPage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const [request, setRequest] = useState<ChangeRequestDetailOut | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showFile, setShowFile] = useState(false);

  const load = useCallback(async () => {
    setRequest(await api.get<ChangeRequestDetailOut>(`/api/thresholds/change-requests/${id}`));
  }, [id]);

  useEffect(() => {
    if (user) load().catch(() => setError("Couldn't load the request."));
  }, [user, load]);

  if (!user) return null;
  if (!request) return <p className="text-sm text-muted-foreground">{error ?? "Loading…"}</p>;

  const act = async (verb: string, body?: object) => {
    setError(null);
    try {
      await api.post(`/api/thresholds/change-requests/${id}/${verb}`, body ?? {});
      setComment("");
      await load();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.code}: ${err.message}` : "Something went wrong.");
    }
  };

  const mine = request.author === user.username;
  const approvedByMe = request.approvals.some((a) => a.user === user.username);

  return (
    <div className="mx-auto flex max-w-[1080px] flex-col gap-4">
      <Link href="/admin/settings/thresholds" className="text-sm text-muted-foreground hover:text-foreground">
        ← Thresholds
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">
            <span className="font-mono">{request.version}</span> · thresholds.yaml
          </h1>
          <p className="text-xs text-muted-foreground">
            Author {request.author ?? "migration"} · {request.state}
            {request.submitted_at && ` · submitted ${new Date(request.submitted_at).toLocaleString()}`} · validated with the boot model ✓ ·
            approvals {request.approvals.length} of 2 · sha256 {request.sha256.slice(0, 12)}…
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {request.state === "draft" && mine && (
            <Button onClick={() => void act("submit")}>
              Submit for review
            </Button>
          )}
          {request.state === "pending" && !mine && !approvedByMe && (
            <Button onClick={() => void act("approve", { comment })}>
              Approve
            </Button>
          )}
          {(request.state === "pending" || request.state === "draft") && (
            <Button variant="outline" disabled={!comment.trim()} onClick={() => void act("reject", { comment })}>
              Reject…
            </Button>
          )}
        </div>
      </header>
      {error && <p className="text-sm text-danger">{error}</p>}

      <Card asChild>
        <section className="p-4">
          <p className="mb-2 text-[11px] uppercase tracking-wider text-muted-foreground">Diff against the loaded file</p>
          <pre className="max-h-[420px] overflow-auto rounded-md bg-muted p-3 text-xs">
            {request.diff
              ? request.diff.split("\n").map((line, i) => (
                  <span
                    key={i}
                    className={
                      line.startsWith("+") && !line.startsWith("+++")
                        ? "text-ok"
                        : line.startsWith("-") && !line.startsWith("---")
                          ? "text-danger"
                          : ""
                    }
                  >
                    {line}
                    {"\n"}
                  </span>
                ))
              : "(no difference)"}
          </pre>
          <Button variant="link" size="inline" className="mt-2 text-xs" onClick={() => setShowFile(!showFile)}>
            {showFile ? "Hide" : "Show"} the whole file
          </Button>
          {showFile && <pre className="mt-2 max-h-[420px] overflow-auto rounded-md bg-muted p-3 text-xs">{request.yaml_text}</pre>}
        </section>
      </Card>

      <Card asChild>
        <section className="flex flex-col gap-3 p-4 text-sm">
          <h2 className="font-medium">Evidence</h2>
          <p>{request.evidence || "—"}</p>
          <Table className="w-full text-left">
            <TableHeader className="text-[11px] uppercase tracking-wider text-muted-foreground">
              <TableRow>
                <TableHead className="py-1.5 font-medium">Approver</TableHead>
                <TableHead className="py-1.5 font-medium">Role</TableHead>
                <TableHead className="py-1.5 font-medium">At</TableHead>
                <TableHead className="py-1.5 font-medium">Comment</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {request.approvals.map((a, i) => (
                <TableRow key={i} className="border-t border-border">
                  <TableCell className="py-2">{String(a.user)}</TableCell>
                  <TableCell className="py-2">{String(a.role)}</TableCell>
                  <TableCell className="py-2">{a.at ? new Date(String(a.at)).toLocaleString() : "—"}</TableCell>
                  <TableCell className="py-2">{String(a.comment ?? "")}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          {request.rejected_reason && <p className="text-danger">Rejected: {request.rejected_reason}</p>}
          {(request.state === "pending" || request.state === "draft") && (
            <Input value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (required to reject)" />
          )}
        </section>
      </Card>
      <p className="text-xs text-muted-foreground">
        After two approvals the SHA-256 is stored; an engineer opens a PR with this exact text. On boot, a file that matches no approved
        request puts every branch in shadow and raises thresholds_unapproved (BR-F9-07).
      </p>
    </div>
  );
}
