"use client";

// KB drafts (F6 · KB drafts 13-828): what is being written, what waits for review.

import Link from "next/link";
import { useEffect, useState } from "react";
import { DraftStateChip, KbTabs, KIND_VI, canEditKb } from "@/components/kb/KbTabs";
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
      .catch(() => setError("Không tải được bản nháp."));
  }, [user, state, mine]);

  if (!user) return null;

  return (
    <div className="mx-auto max-w-[1180px]">
      <KbTabs user={user} />
      <header className="mb-4 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">Bản nháp · Drafts</h1>
          <p className="text-xs text-muted-foreground">
            Bản nháp không bao giờ được truy xuất; một người khác duyệt trước khi xuất bản (BR-F6-01, 02).
          </p>
        </div>
        <div className="flex items-end gap-3 text-sm">
          <label className="flex items-center gap-1.5">
            <Checkbox checked={mine} onCheckedChange={(checked) => setMine(checked === true)} />
            Của tôi
          </label>
          <NativeSelect aria-label="State" value={state} onChange={(e) => setState(e.target.value)}>
            {STATES.map((s) => (
              <option key={s} value={s}>
                {s || "Tất cả"}
              </option>
            ))}
          </NativeSelect>
          <Button asChild>
            <Link href="/kb/drafts/new">
              Trang mới
            </Link>
          </Button>
        </div>
      </header>

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
            {rows?.length === 0 && (
              <TableRow>
                <TableCell colSpan={6} className="px-4 py-6 text-center text-muted-foreground">
                  Không có bản nháp.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </Card>
    </div>
  );
}
