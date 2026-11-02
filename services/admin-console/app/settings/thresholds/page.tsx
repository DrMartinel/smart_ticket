"use client";

// Thresholds (F9 · Threshold history 16-1436): the loaded file and its approval, every change
// request, and a new one: the whole file, validated with the boot model (BR-F9-05).

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { ChangeRequestDetailOut, ChangeRequestOut, CurrentThresholdsOut } from "@/lib/types/generated";

const STATE_TONE: Record<string, string> = {
  draft: "",
  pending: "tone-warn",
  approved: "tone-ok",
  loaded: "tone-ok",
  rejected: "tone-danger",
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
          <p className="text-xs text-[var(--text-muted)]">
            thresholds.yaml is the only home of tunables. A change is the whole file, approved by two people who aren&apos;t its author,
            then shipped by PR under its request id (ADR-0035).
          </p>
        </div>
        {mayPropose && !composing && (
          <button className="btn btn-primary" onClick={startDraft} disabled={!current}>
            New change request
          </button>
        )}
      </header>

      {current && (
        <section className={`card p-4 text-sm ${current.approved ? "" : "border-[var(--danger)]"}`}>
          <p className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">Loaded file</p>
          <p className="mt-1 text-lg font-semibold">{current.change_request ?? current.version}</p>
          <p className="text-xs text-[var(--text-muted)]">
            {current.approved ? "approved" : "NOT approved: every branch is in shadow"}
            {!current.checked && " · approval check off (THRESHOLDS_REQUIRE_APPROVAL=false)"} · sha256 {current.sha256.slice(0, 12)}…
            {current.loaded_at && ` · loaded ${new Date(current.loaded_at).toLocaleString()}`}
          </p>
        </section>
      )}

      {composing && (
        <section className="card flex flex-col gap-3 p-4 text-sm">
          <p className="text-xs text-[var(--text-muted)]">
            The file must keep <code>version: &quot;{current?.next_version}&quot;</code>: that is this request&apos;s id, and the text that
            ships must be the text that was approved.
          </p>
          <textarea className="field min-h-[360px] font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} spellCheck={false} />
          <input className="field" value={evidence} onChange={(e) => setEvidence(e.target.value)} placeholder="Evidence: calibration run id, evals/HISTORY.md entry" />
          {error && <p className="text-[var(--danger)]">{error}</p>}
          <div className="flex gap-2">
            <button className="btn btn-primary" onClick={() => void create()}>
              Validate and save draft
            </button>
            <button className="btn btn-secondary" onClick={() => setComposing(false)}>
              Cancel
            </button>
          </div>
        </section>
      )}

      <section className="card overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-[11px] uppercase tracking-wider text-[var(--text-muted)]">
            <tr>
              <th className="px-4 py-2.5 font-medium">Version</th>
              <th className="px-4 py-2.5 font-medium">State</th>
              <th className="px-4 py-2.5 font-medium">Author</th>
              <th className="px-4 py-2.5 font-medium">Approvals</th>
              <th className="px-4 py-2.5 font-medium">Created</th>
              <th className="px-4 py-2.5 font-medium">Loaded</th>
            </tr>
          </thead>
          <tbody>
            {history.map((r) => (
              <tr key={r.id} className="border-t border-[var(--border)]">
                <td className="px-4 py-2.5">
                  <Link href={`/settings/thresholds/${r.id}`} className="font-mono text-[var(--accent)] hover:underline">
                    {r.version}
                  </Link>
                </td>
                <td className="px-4 py-2.5">
                  <span className={`badge ${STATE_TONE[r.state] ?? ""}`}>{r.state}</span>
                </td>
                <td className="px-4 py-2.5">{r.author ?? "migration"}</td>
                <td className="px-4 py-2.5">{r.approvals.map((a) => String(a.user)).join(", ") || "—"}</td>
                <td className="px-4 py-2.5">{new Date(r.created_at).toLocaleDateString()}</td>
                <td className="px-4 py-2.5">{r.loaded_at ? new Date(r.loaded_at).toLocaleString() : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}
