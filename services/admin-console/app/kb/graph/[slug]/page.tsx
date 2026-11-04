"use client";

// A KB page's entity graph (F11 UC-F11-01..03): its pointers, editors' corrections and rebuilds.

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { KbTabs, canEditKb } from "@/components/kb/KbTabs";
import { api, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { dateTime } from "@/lib/format";
import type { GraphEdgeOut, PageGraphOut, RebuildRequestOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";

const REBUILD_STATE_VI: Record<string, string> = {
  pending: "Waiting",
  done: "Xong",
  failed: "Failed",
};

type Correction = { target: string; action: "hide" | "add" | "remove" } | null;

function Build({ label, request }: { label: string; request: RebuildRequestOut | null }) {
  return (
    <Card className="p-4 text-sm">
      <p className="text-[11px] uppercase tracking-wider text-muted-foreground">{label}</p>
      {request ? (
        <>
          <p className="mt-1 font-medium">
            {REBUILD_STATE_VI[request.state] ?? request.state} · {request.reason === "manual" ? "requested by hand" : "after publish"}
          </p>
          <p className="text-xs text-muted-foreground">
            {dateTime(request.done_at ?? request.requested_at)}
            {request.build_id && <span className="block truncate font-mono">{request.build_id}</span>}
          </p>
        </>
      ) : (
        <p className="mt-1 text-muted-foreground">—</p>
      )}
    </Card>
  );
}

function EdgeTable({
  title,
  edges,
  editor,
  outgoing,
  onCorrect,
  onConfirm,
}: {
  title: string;
  edges: GraphEdgeOut[];
  editor: boolean;
  outgoing: boolean;
  onCorrect: (c: Correction) => void;
  onConfirm: (target: string) => void;
}) {
  return (
    <Card asChild>
      <section className="mb-5 overflow-x-auto">
        <h2 className="border-b border-border px-4 py-3 text-sm font-semibold">
          {title} <span className="font-normal text-muted-foreground">({edges.length})</span>
        </h2>
        {edges.length === 0 ? (
          <p className="px-4 py-6 text-center text-sm text-muted-foreground">No links yet.</p>
        ) : (
          <Table className="min-w-[640px] table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead>Trang · Page</TableHead>
                <TableHead className="w-16 text-right">Score</TableHead>
                <TableHead>Evidence</TableHead>
                <TableHead className="w-36">State</TableHead>
                {editor && outgoing && <TableHead className="w-28" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {edges.map((e) => (
                <TableRow key={e.slug} className="align-top">
                  <TableCell className="py-3">
                    <Link href={`/kb/graph/${encodeURIComponent(e.slug)}`} className="block truncate font-medium hover:text-primary">
                      {e.title}
                    </Link>
                    <span className="block truncate font-mono text-xs text-muted-foreground">{e.slug}</span>
                  </TableCell>
                  <TableCell className="py-3 text-right font-mono tabular-nums">{e.score ?? "—"}</TableCell>
                  <TableCell className="py-3 text-xs">
                    {e.evidence.length > 0 ? (
                      <>
                        <span className="line-clamp-2">{e.evidence[0]}</span>
                        {e.evidence.length > 1 && <span className="text-muted-foreground">+{e.evidence.length - 1} more pairs</span>}
                      </>
                    ) : (
                      <span className="text-muted-foreground">Added by an editor</span>
                    )}
                  </TableCell>
                  <TableCell className="py-3">
                    <div className="flex flex-wrap gap-1">
                      {e.stale && <Badge variant="warn">Cũ · stale</Badge>}
                      {e.reviewed && <Badge variant="ok">Confirmed</Badge>}
                      {e.override?.action === "hide" && <Badge variant="danger">Ẩn</Badge>}
                      {e.override?.action === "add" && <Badge variant="info">Added by hand</Badge>}
                    </div>
                    {e.override && (
                      <p className="mt-1 text-xs text-muted-foreground">
                        “{e.override.reason}” · {e.override.created_by}
                      </p>
                    )}
                  </TableCell>
                  {editor && outgoing && (
                    <TableCell className="py-3 text-right">
                      <span className="inline-flex flex-wrap justify-end gap-2 text-xs">
                        {e.score !== null && !e.reviewed && !e.override && (
                          <Button variant="link" size="inline"  onClick={() => onConfirm(e.slug)}>
                            Confirm
                          </Button>
                        )}
                        {!e.override && (
                          <Button variant="link" size="inline" className="text-danger" onClick={() => onCorrect({ target: e.slug, action: "hide" })}>
                            Ẩn
                          </Button>
                        )}
                        {e.override && (
                          <Button variant="link" size="inline"  onClick={() => onCorrect({ target: e.slug, action: "remove" })}>
                            Undo correction
                          </Button>
                        )}
                      </span>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </Card>
  );
}

export default function PageGraphPage() {
  const user = useRequireAuth();
  const { slug } = useParams<{ slug: string }>();
  const page = decodeURIComponent(slug);
  const [graph, setGraph] = useState<PageGraphOut | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [correction, setCorrection] = useState<Correction>(null);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    api
      .get<PageGraphOut>(`/api/kb/${encodeURIComponent(page)}/graph`)
      .then(setGraph)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Couldn't load the page graph."));
  }, [page]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  if (!user) return null;
  const editor = (user.capabilities ?? []).includes("kb_editor");

  const run = async (call: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await call();
      setCorrection(null);
      setTarget("");
      setReason("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message}${err.code ? ` (${err.code})` : ""}` : "Couldn't save. Try again.");
    } finally {
      setBusy(false);
    }
  };

  const base = `/api/kb/${encodeURIComponent(page)}/graph`;
  const submit = () => {
    if (!correction) return;
    if (correction.action === "remove") {
      return run(() => api.delete(`${base}/overrides/${encodeURIComponent(correction.target)}`, { reason }));
    }
    return run(() => api.post(`${base}/overrides`, { target: correction.target || target.trim(), action: correction.action, reason }));
  };

  return (
    <div className="mx-auto max-w-[1280px]">
      <KbTabs user={user} />
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Page graph</h1>
          <p className="font-mono text-xs text-muted-foreground">{page}</p>
          <p className="mt-1 max-w-[720px] text-xs text-muted-foreground">
            Links search follows to reach the page with the fix. Scores only order the links; they never decide an automatic answer.
          </p>
        </div>
        <div className="flex gap-2">
          {editor && (
            <Button variant="outline" onClick={() => setCorrection({ target: "", action: "add" })}>
              Add link
            </Button>
          )}
          {canEditKb(user) && (
            <Button
              disabled={busy || Boolean(graph?.pending_request)}
              onClick={() => void run(() => api.post(`${base}/rebuild`))}
            >
              Rebuild
            </Button>
          )}
        </div>
      </header>

      {error && <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}

      {correction && (
        <Card asChild>
          <form
            className="mb-5 flex flex-wrap items-end gap-2 p-4 text-sm"
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <p className="w-full font-medium">
              {correction.action === "hide" && `Hide the link to ${correction.target}`}
              {correction.action === "remove" && `Undo the correction for ${correction.target}`}
              {correction.action === "add" && "Add a link to a page (followed first)"}
            </p>
            {correction.action === "add" && (
              <Input className="w-80 font-mono" placeholder="target page slug" aria-label="Target page slug" value={target} onChange={(e) => setTarget(e.target.value)} required autoFocus />
            )}
            <Input
              className="min-w-[280px] flex-1"
              placeholder="Reason (required, logged)" aria-label="Reason"
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              required
              autoFocus={correction.action !== "add"}
            />
            <Button type="submit" disabled={busy}>
              Save
            </Button>
            <Button variant="outline" type="button" onClick={() => setCorrection(null)}>
              Cancel
            </Button>
          </form>
        </Card>
      )}

      {graph === null && !error && <p className="text-sm text-muted-foreground">Loading…</p>}
      {graph && (
        <>
          <div className="mb-5 grid grid-cols-1 gap-4 md:grid-cols-2">
            <Build label="Last build" request={graph.last_build} />
            <Build label="Pending" request={graph.pending_request} />
          </div>
          <EdgeTable
            title="Outgoing"
            edges={graph.outgoing}
            editor={editor}
            outgoing
            onCorrect={setCorrection}
            onConfirm={(t) => void run(() => api.post(`${base}/edges/${encodeURIComponent(t)}/confirm`))}
          />
          <EdgeTable
            title="Incoming"
            edges={graph.incoming}
            editor={editor}
            outgoing={false}
            onCorrect={setCorrection}
            onConfirm={() => undefined}
          />
        </>
      )}
    </div>
  );
}
