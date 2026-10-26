"use client";

// One threshold change request (F9 · Threshold change request 16-1336): the diff against the loaded
// file, the evidence, and the approvals; two, neither by the author, one a manager's.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { ChangeRequestDetailOut } from "@/lib/types/generated";

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
  if (!request) return <p className="text-sm text-[var(--text-muted)]">{error ?? "Loading…"}</p>;

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
      <Link href="/settings/thresholds" className="text-sm text-[var(--text-muted)] hover:text-[var(--text)]">
        ← Thresholds
      </Link>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">
            <span className="font-mono">{request.version}</span> · thresholds.yaml
          </h1>
          <p className="text-xs text-[var(--text-muted)]">
            Author {request.author ?? "migration"} · {request.state}
            {request.submitted_at && ` · submitted ${new Date(request.submitted_at).toLocaleString()}`} · validated with the boot model ✓ ·
            approvals {request.approvals.length} of 2 · sha256 {request.sha256.slice(0, 12)}…
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {request.state === "draft" && mine && (
            <button className="btn btn-primary" onClick={() => void act("submit")}>
              Submit for review
            </button>
          )}
          {request.state === "pending" && !mine && !approvedByMe && (
            <button className="btn btn-primary" onClick={() => void act("approve", { comment })}>
              Approve
            </button>
          )}
          {(request.state === "pending" || request.state === "draft") && (
            <button className="btn btn-secondary" disabled={!comment.trim()} onClick={() => void act("reject", { comment })}>
              Reject…
            </button>
          )}
        </div>
      </header>
      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}

      <section className="card p-4">
        <p className="mb-2 text-[11px] uppercase tracking-wider text-[var(--text-muted)]">Diff against the loaded file</p>
        <pre className="max-h-[420px] overflow-auto rounded-[5px] bg-[var(--surface-2)] p-3 text-xs">
          {request.diff
            ? request.diff.split("\n").map((line, i) => (
                <span
                  key={i}
                  className={
                    line.startsWith("+") && !line.startsWith("+++")
                      ? "text-[var(--ok)]"
                      : line.startsWith("-") && !line.startsWith("---")
                        ? "text-[var(--danger)]"
                        : ""
                  }
                >
                  {line}
                  {"\n"}
                </span>
              ))
            : "(no difference)"}
        </pre>
        <button className="mt-2 text-xs text-[var(--accent)]" onClick={() => setShowFile(!showFile)}>
          {showFile ? "Hide" : "Show"} the whole file
        </button>
        {showFile && <pre className="mt-2 max-h-[420px] overflow-auto rounded-[5px] bg-[var(--surface-2)] p-3 text-xs">{request.yaml_text}</pre>}
      </section>

      <section className="card flex flex-col gap-3 p-4 text-sm">
        <h2 className="font-medium">Evidence</h2>
        <p>{request.evidence || "—"}</p>
        <table className="w-full text-left">
          <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            <tr>
              <th className="py-1.5 font-medium">Approver</th>
              <th className="py-1.5 font-medium">Role</th>
              <th className="py-1.5 font-medium">At</th>
              <th className="py-1.5 font-medium">Comment</th>
            </tr>
          </thead>
          <tbody>
            {request.approvals.map((a, i) => (
              <tr key={i} className="border-t border-[var(--border)]">
                <td className="py-2">{String(a.user)}</td>
                <td className="py-2">{String(a.role)}</td>
                <td className="py-2">{a.at ? new Date(String(a.at)).toLocaleString() : "—"}</td>
                <td className="py-2">{String(a.comment ?? "")}</td>
              </tr>
            ))}
          </tbody>
        </table>
        {request.rejected_reason && <p className="text-[var(--danger)]">Rejected: {request.rejected_reason}</p>}
        {(request.state === "pending" || request.state === "draft") && (
          <input className="field" value={comment} onChange={(e) => setComment(e.target.value)} placeholder="Comment (required to reject)" />
        )}
      </section>
      <p className="text-xs text-[var(--text-muted)]">
        After two approvals the SHA-256 is stored; an engineer opens a PR with this exact text. On boot, a file that matches no approved
        request puts every branch in shadow and raises thresholds_unapproved (BR-F9-07).
      </p>
    </div>
  );
}
