"use client";

// The weekly KB-gap report (F6 · KB gaps 13-1299): refused tickets by topic, each a gap (no page)
// or an update (a page that doesn't answer them).

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";
import { KbTabs } from "@/components/kb/KbTabs";
import { vnTime } from "@/components/security/badges";
import { api, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { GapReportOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";

const SAMPLES = 3;

export default function GapsPage() {
  const user = useRequireAuth();
  const [report, setReport] = useState<GapReportOut | null>(null);
  const [dismissing, setDismissing] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<GapReportOut>("/api/kb/gaps")
      .then(setReport)
      .catch(() => setError("Couldn't load the gap report."));
  }, []);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  if (!user) return null;

  const dismiss = async (id: string) => {
    setError(null);
    try {
      await api.post(`/api/kb/gaps/${id}/dismiss`, { reason });
      setDismissing(null);
      setReason("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message}${err.code ? ` (${err.code})` : ""}` : "Couldn't hide the topic. Try again.");
    }
  };

  return (
    <div className="mx-auto max-w-[1180px]">
      <KbTabs user={user} />
      <header className="mb-4">
        <h1 className="text-xl font-semibold">
          KB gaps
          {report?.window_start && report.window_end && (
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {vnTime(report.window_start)} – {vnTime(report.window_end)}
            </span>
          )}
        </h1>
        <p className="text-xs text-muted-foreground">
          Groups of tickets no help page answered, and tickets a reviewer marked as citing the wrong page. Only masked subjects
          are shown. {report ? `${report.tickets_considered} tickets considered.` : ""}
        </p>
      </header>

      {error && <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}

      <Card className="overflow-x-auto">
        <Table className="min-w-[900px]">
          <TableHeader>
            <TableRow>
              <TableHead>Tickets</TableHead>
              <TableHead>Sample subjects</TableHead>
              <TableHead>Nearest live page</TableHead>
              <TableHead>Similarity</TableHead>
              <TableHead>Label</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {report?.clusters.map((c) => (
              <TableRow key={c.id} className="align-top">
                <TableCell>{c.size}</TableCell>
                <TableCell>
                  {c.tickets.slice(0, SAMPLES).map((t) => (
                    <div key={t.public_id} className="text-xs">
                      <Link href={`/tickets/${t.public_id}`} className="text-primary">
                        {t.public_id}
                      </Link>{" "}
                      · {t.subject_masked}
                    </div>
                  ))}
                  {c.tickets.length > SAMPLES && <div className="text-xs text-muted-foreground">+{c.tickets.length - SAMPLES} more tickets</div>}
                </TableCell>
                <TableCell className="num text-xs">{c.nearest_slug ?? "—"}</TableCell>
                <TableCell>{c.nearest_similarity?.toFixed(2) ?? "—"}</TableCell>
                <TableCell>
                  <Badge variant={c.label === "update" ? "info" : "warn"}>{c.label}</Badge>
                </TableCell>
                <TableCell className="text-right">
                  {c.draft_id ? (
                    <Link href={`/kb/drafts/${c.draft_id}`} className="text-primary hover:underline">
                      View draft
                    </Link>
                  ) : dismissing === c.id ? (
                    <form
                      className="flex items-center gap-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        void dismiss(c.id);
                      }}
                    >
                      <Input className="w-48" placeholder="e.g. not an IT question" aria-label="Reason to hide" value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
                      <Button variant="outline" size="xs" type="submit">
                        Ẩn
                      </Button>
                    </form>
                  ) : (
                    <div className="flex flex-col items-end gap-1">
                      <Button asChild variant="outline" size="sm">
                        <Link
                          className="text-xs"
                          href={
                            c.label === "update" && c.nearest_slug
                              ? `/kb/drafts/new?kind=edit&slug=${encodeURIComponent(c.nearest_slug)}&gap=${c.id}`
                              : `/kb/drafts/new?kind=create&gap=${c.id}`
                          }
                        >
                          {c.label === "update" ? "Edit the page" : "Write a new page"}
                        </Link>
                      </Button>
                      <Button variant="link" size="inline" className="text-xs" onClick={() => setDismissing(c.id)}>
                        Hide topic…
                      </Button>
                    </div>
                  )}
                </TableCell>
              </TableRow>
            ))}
            {report && report.clusters.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="px-4 py-6 text-center text-muted-foreground">
                  {report.id ? "No topic is big enough to report yet." : "No report yet. It runs every Monday at 06:00."}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
      <p className="mt-2 text-xs text-muted-foreground">
        “Update” means the nearest existing chunk is similar enough to edit that page. Hidden topics don't appear in
        kb_gaps.dismiss_days ngày.
      </p>
    </div>
  );
}
