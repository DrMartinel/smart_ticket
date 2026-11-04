"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, TableStatus } from "@/components/ui/states";

// The authority queue (F6 · Authority queue 13-1049): pages a manager must grant, re-grant or
// re-tier. A grant pins the text the manager read (BR-F6-05); high-risk pages go one at a time.

import { Fragment, useCallback, useEffect, useState } from "react";
import { AUTHORITY_REASON_VI, DiffLines } from "@/components/kb/KbTabs";
import { vnTime } from "@/components/security/badges";
import { api, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { riskTierTone } from "@/lib/badges";
import type { AuthorityQueueItemOut, BulkAllowedOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Checkbox } from "@/components/ui/checkbox";
import { SectionTabs } from "@/components/TabNav";

export default function AuthorityQueuePage() {
  const user = useRequireAuth();
  const [items, setItems] = useState<AuthorityQueueItemOut[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState<string | null>(null);
  const [read, setRead] = useState(false);
  const [reason, setReason] = useState("");
  const [tier, setTier] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<AuthorityQueueItemOut[]>("/api/kb/authority-queue")
      .then((r) => {
        setItems(r);
        setSelected(new Set());
      })
      .catch(() => setError("Couldn't load the authority queue."));
  }, []);

  useEffect(() => {
    if (user?.role === "manager") load();
  }, [user, load]);

  if (!user) return null;

  const run = async (call: () => Promise<unknown>, done: string) => {
    setError(null);
    setNotice(null);
    if (!read || !reason.trim()) {
      setError("Confirm you've read the text, and give a reason.");
      return;
    }
    try {
      await call();
      setNotice(done);
      setReason("");
      setRead(false);
      setOpen(null);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message}${err.code ? ` (${err.code})` : ""}` : "That didn't go through. Try again.");
    }
  };

  const grant = (slug: string, allowed: boolean) =>
    run(() => api.post(`/api/kb/${slug}/auto-reply-allowed`, { allowed, reason: reason.trim() }), allowed ? "Auto-reply allowed." : "Kept without auto-reply.");
  const retier = (slug: string) =>
    run(() => api.post(`/api/kb/${slug}/risk-tier`, { risk_tier: tier, reason: reason.trim() }), "Risk tier changed.");
  const bulk = () =>
    run(async () => {
      const r = await api.post<BulkAllowedOut>("/api/kb/auto-reply-allowed/bulk", {
        slugs: [...selected],
        allowed: true,
        reason: reason.trim(),
      });
      return r;
    }, `Auto-reply allowed on ${selected.size} pages.`);

  const toggle = (slug: string) => {
    const next = new Set(selected);
    if (next.has(slug)) next.delete(slug);
    else next.add(slug);
    setSelected(next);
  };

  const confirmBox = (
    <>
      <label className="flex items-center gap-2 text-sm">
        <Checkbox checked={read} onCheckedChange={(checked) => setRead(checked === true)} />
        I have read this text
      </label>
      <label className="flex flex-col gap-1 text-sm">
        <span className="text-xs text-muted-foreground">Reason</span>
        <Input value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
    </>
  );

  return (
    <Page className="flex flex-col gap-4">
      <SectionTabs />
      <PageHeader
        className="mb-2"
        eyebrow="Admin / Help pages"
        vi="Hàng chờ quyền"
        title="Authority queue"
        description={<>Pages waiting for a decision on automatic answers. When you allow one, the SHA-256 of the text you read is recorded, so any later edit revokes it.</>}
      />

      {error && <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}
      {notice && <Alert variant="ok" className="mb-3 text-sm"><AlertDescription>{notice}</AlertDescription></Alert>}

      <Card className="overflow-x-auto">
        <Table className="min-w-[860px]">
          <TableHeader>
            <TableRow>
              <TableHead className="w-10" />
              <TableHead>Page</TableHead>
              <TableHead>Risk</TableHead>
              <TableHead>Why here</TableHead>
              <TableHead>Since</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            {items?.map((i) => {
              const high = i.article.risk_tier === "high";
              const slug = i.article.slug;
              return (
                <Fragment key={slug}>
                  <TableRow className={`${high ? "bg-danger-soft" : ""}`}>
                    <TableCell>
                      <Checkbox
                        aria-label={`Select ${slug}`}
                        disabled={high}
                        checked={selected.has(slug)}
                        onCheckedChange={() => toggle(slug)}
                      />
                    </TableCell>
                    <TableCell>
                      <div className="font-mono">{slug}</div>
                      <div className="text-xs text-muted-foreground">{i.article.title}</div>
                    </TableCell>
                    <TableCell>
                      <Badge variant={riskTierTone(i.article.risk_tier)}>{i.article.risk_tier}</Badge>
                      {i.proposed_risk_tier && i.proposed_risk_tier !== i.article.risk_tier && (
                        <span className="ml-1 text-xs text-muted-foreground">→ {i.proposed_risk_tier}</span>
                      )}
                    </TableCell>
                    <TableCell>{AUTHORITY_REASON_VI[i.reason] ?? i.reason}</TableCell>
                    <TableCell>{i.published_at ? vnTime(i.published_at) : "—"}</TableCell>
                    <TableCell className="text-right">
                      <Button
                        variant="link"
                        size="inline"
                        className={high ? "text-danger" : undefined}
                        onClick={() => {
                          setOpen(open === slug ? null : slug);
                          setTier(i.proposed_risk_tier ?? i.article.risk_tier);
                        }}
                      >
                        {high ? "Review alone" : "Read the text"}
                      </Button>
                    </TableCell>
                  </TableRow>
                  {open === slug && (
                    <TableRow className="bg-muted">
                      <TableCell colSpan={6} className="px-4 py-4">
                        <div className="flex flex-col gap-3">
                          {i.change_note && <p className="text-sm">Ghi chú: {i.change_note}</p>}
                          {i.published_by && <p className="text-xs text-muted-foreground">Published by {i.published_by}</p>}
                          <div className="text-xs text-muted-foreground">Changes from the previous text</div>
                          <DiffLines lines={[...i.title_diff, ...i.body_diff]} />
                          {confirmBox}
                          <div className="flex flex-wrap items-end justify-end gap-2">
                            <NativeSelect wrapperClassName="w-32" aria-label="Risk tier" value={tier} onChange={(e) => setTier(e.target.value)}>
                              {["low", "medium", "high"].map((t) => (
                                <option key={t}>{t}</option>
                              ))}
                            </NativeSelect>
                            <Button variant="outline" disabled={tier === i.article.risk_tier} onClick={() => void retier(slug)}>
                              Change risk tier
                            </Button>
                            <Button variant="outline" onClick={() => void grant(slug, false)}>
                              Don't allow
                            </Button>
                            <Button disabled={i.article.risk_tier !== tier} onClick={() => void grant(slug, true)}>
                              Allow automatic answers
                            </Button>
                          </div>
                        </div>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              );
            })}
            <TableStatus colSpan={6} rows={items} error={!!error} empty={<EmptyState compact title="No pages are waiting for a decision" />} />
          </TableBody>
        </Table>
      </Card>

      {selected.size > 0 && open === null && (
        <Card asChild>
          <section className="mt-4 flex flex-col gap-3 p-5">
            <h2 className="eyebrow !text-foreground/80">Approve {selected.size} pages</h2>
            {confirmBox}
            <p className="text-xs text-danger">
              High-risk pages are always reviewed one at a time; a bulk request that includes one is refused and no page
              is approved.
            </p>
            <div className="flex justify-end">
              <Button onClick={() => void bulk()}>
                Approve selected pages ({selected.size})
              </Button>
            </div>
          </section>
        </Card>
      )}
    </Page>
  );
}
