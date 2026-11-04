"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState, TableStatus } from "@/components/ui/states";

// KB drafts (F6 · KB drafts 13-828): what is being written, what waits for review.

import Link from "next/link";
import { useEffect, useState } from "react";
import { DRAFT_STATE_VI, DraftStateChip, KbTabs, KIND_VI, canEditKb } from "@/components/kb/KbTabs";
import { vnTime } from "@/components/security/badges";
import { api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { DraftOut } from "@/lib/types/generated";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Checkbox } from "@/components/ui/checkbox";

const STATES = ["", "draft", "in_review", "changes_requested", "conflict", "published", "withdrawn"];

export default function DraftsPage() {
  const user = useRequireAuth();
  const [state, setState] = useState("in_review");
  const [mine, setMine] = useState(false);
  const [rows, setRows] = useState<DraftOut[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!user || !canEditKb(user)) return;
    const params = new URLSearchParams({ limit: "100" });
    if (state) params.set("state", state);
    if (mine) params.set("author", user.username);
    api
      .get<{ items: DraftOut[] }>(`/api/kb/drafts?${params}`)
      .then((page) => {
        setRows(page.items);
        setError(null);
      })
      .catch(() => setError("Couldn't load drafts."));
  }, [user, state, mine]);

  if (!user) return null;

  return (
    <Page className="flex flex-col gap-4">
      <KbTabs user={user} />
      <PageHeader
        className="mb-2"
        eyebrow="Knowledge / Drafts"
        vi="Bản nháp"
        title="Drafts"
        description={<>Drafts are never used for answers. Someone other than the author reviews each one before it's published.</>}
        actions={
      <>
      <div className="flex items-end gap-3 text-sm">
        <label className="flex items-center gap-1.5">
          <Checkbox checked={mine} onCheckedChange={(checked) => setMine(checked === true)} />
          Mine
        </label>
        <NativeSelect aria-label="State" value={state} onChange={(e) => setState(e.target.value)}>
          {STATES.map((s) => (
            <option key={s} value={s}>
              {s ? (DRAFT_STATE_VI[s] ?? s) : "All"}
            </option>
          ))}
        </NativeSelect>
        <Button asChild>
          <Link href="/kb/drafts/new">
            New page
          </Link>
        </Button>
      </div>
      </>
      }
      />

      {error && <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}

      <Card className="overflow-x-auto">
        <Table className="min-w-[820px]">
          <TableHeader>
            <TableRow>
              <TableHead>Page</TableHead>
              <TableHead>Kind</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Author</TableHead>
              <TableHead>Reviewer</TableHead>
              <TableHead>Updated</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {rows?.map((d) => (
              <TableRow key={d.id}>
                <TableCell>
                  <Link href={`/kb/drafts/${d.id}`} className="font-medium text-primary hover:underline">
                    {d.title}
                  </Link>
                  <div className="font-mono text-xs text-muted-foreground">{d.slug}</div>
                </TableCell>
                <TableCell>{KIND_VI[d.kind] ?? d.kind}</TableCell>
                <TableCell>
                  <DraftStateChip state={d.state} />
                </TableCell>
                <TableCell>{d.author.username}</TableCell>
                <TableCell>{d.reviewer?.username ?? "—"}</TableCell>
                <TableCell>{vnTime(d.updated_at)}</TableCell>
              </TableRow>
            ))}
            <TableStatus colSpan={6} rows={rows} error={!!error} empty={<EmptyState compact title="No drafts here" />} />
          </TableBody>
        </Table>
      </Card>
    </Page>
  );
}
