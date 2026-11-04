"use client";

import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState, TableStatus } from "@/components/ui/states";

// One KB draft: the author edits it (F6 · KB editor 13-737); another editor or a manager reviews
// it against the live page (F6 · Draft review 13-981).

import Link from "next/link";
import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { DiffLines, DraftStateChip, KbTabs, KIND_VI } from "@/components/kb/KbTabs";
import { api, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { DraftDiffOut, DraftOut, GapReportOut } from "@/lib/types/generated";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Alert, AlertDescription } from "@/components/ui/alert";

const CATEGORIES = ["access", "network", "hardware", "software", "security", "other"];
const TIERS = ["low", "medium", "high"];
const EDITABLE = ["draft", "changes_requested"];

type Form = Pick<DraftOut, "title" | "body" | "category" | "proposed_risk_tier" | "change_note">;

export default function DraftPage() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const [draft, setDraft] = useState<DraftOut | null>(null);
  const [form, setForm] = useState<Form | null>(null);
  const [diff, setDiff] = useState<DraftDiffOut | null>(null);
  const [showChunks, setShowChunks] = useState(false);
  const [gap, setGap] = useState<GapReportOut["clusters"][number] | null>(null);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    api
      .get<DraftOut>(`/api/kb/drafts/${id}`)
      .then((d) => {
        setDraft(d);
        setForm({
          title: d.title,
          body: d.body,
          category: d.category,
          proposed_risk_tier: d.proposed_risk_tier,
          change_note: d.change_note,
        });
      })
      .catch(() => setError("Couldn't load this draft."));
    api.get<DraftDiffOut>(`/api/kb/drafts/${id}/diff`).then(setDiff).catch(() => setDiff(null));
  }, [id]);

  useEffect(() => {
    if (user) load();
  }, [user, load]);

  useEffect(() => {
    if (!draft?.gap_cluster_id) return;
    api
      .get<GapReportOut>("/api/kb/gaps")
      .then((r) => setGap(r.clusters.find((c) => c.id === draft.gap_cluster_id) ?? null))
      .catch(() => setGap(null));
  }, [draft?.gap_cluster_id]);

  if (!user) return null;
  if (!draft || !form) {
    return (
      <div className="mx-auto max-w-[1180px]">
        <KbTabs user={user} />
        {error ? <Alert variant="danger" className="text-sm"><AlertDescription>{error}</AlertDescription></Alert> : <p className="text-sm text-muted-foreground">Loading…</p>}
      </div>
    );
  }

  const isAuthor = draft.author.id === user.id;
  const editing = isAuthor && EDITABLE.includes(draft.state) && draft.kind !== "retire";
  const reviewing = !isAuthor && draft.state === "in_review";

  const run = async (call: () => Promise<unknown>, done?: string) => {
    setError(null);
    setNotice(null);
    try {
      await call();
      if (done) setNotice(done);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message}${err.code ? ` (${err.code})` : ""}` : "That didn't go through. Try again.");
    }
  };

  const save = () => api.patch(`/api/kb/drafts/${id}`, form);
  const act = (action: string, body?: unknown) => api.post(`/api/kb/drafts/${id}/${action}`, body);

  return (
    <Page className="flex flex-col gap-4">
      <KbTabs user={user} />
      <PageHeader
        className="mb-2"
        eyebrow="Knowledge / Draft"
        title={<>{reviewing ? "Review" : KIND_VI[draft.kind]} · <span className="font-mono">{draft.slug}</span></>}
        description={<><DraftStateChip state={draft.state} />
            <span>by {draft.author.username}</span>
            {draft.base_version !== null && <span>· based on version {draft.base_version}</span>}
            <span>· proposed risk {draft.proposed_risk_tier}</span>
            {draft.state !== "published" && <span>· not used for answers until published</span>}</>}
        actions={
      <>
      <div className="flex flex-wrap gap-2">
        {editing && (
          <>
            <Button variant="outline" onClick={() => void run(save, "Draft saved.")}>
              Save draft
            </Button>
            <Button variant="outline" onClick={() => setShowChunks(!showChunks)}>
              Preview chunks
            </Button>
            <Button onClick={() => void run(async () => (await save(), act("submit")), "Sent for review.")}>
              Send for review
            </Button>
          </>
        )}
        {isAuthor && draft.kind === "retire" && EDITABLE.includes(draft.state) && (
          <Button onClick={() => void run(() => act("submit"), "Sent for review.")}>
            Send for review
          </Button>
        )}
        {isAuthor && draft.state === "conflict" && (
          <Button onClick={() => void run(() => act("rebase"), "Updated to the current page.")}>
            Update to the current page
          </Button>
        )}
        {(isAuthor || user.role === "manager") && [...EDITABLE, "conflict"].includes(draft.state) && (
          <Button variant="outline" onClick={() => void run(() => act("withdraw"), "Draft withdrawn.")}>
            Rút
          </Button>
        )}
      </div>
      </>
      }
      />

      {error && <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}
      {notice && <Alert variant="ok" className="mb-3 text-sm"><AlertDescription>{notice}</AlertDescription></Alert>}
      {draft.review_comment && draft.state === "changes_requested" && (
        <Alert variant="warn" className="mb-3 text-sm">
          <AlertDescription>
            {draft.reviewer?.username}: {draft.review_comment}
          </AlertDescription>
        </Alert>
      )}
      {draft.state === "conflict" && (
        <Alert variant="danger" className="mb-3 text-sm">
          <AlertDescription>
            The page changed after this draft was started. The author updates the draft to the current page, then sends it for review again.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_330px]">
        <div className="flex flex-col gap-4">
          {editing ? (
            <Card asChild>
              <section className="flex flex-col gap-3 p-5 text-sm">
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Title</span>
                  <Input value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
                </label>
                <div className="flex flex-wrap gap-3">
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-muted-foreground">Category</span>
                    <NativeSelect wrapperClassName="w-44" value={form.category} onChange={(e) => setForm({ ...form, category: e.target.value })}>
                      {CATEGORIES.map((c) => (
                        <option key={c}>{c}</option>
                      ))}
                    </NativeSelect>
                  </label>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-muted-foreground">Proposed risk tier</span>
                    <NativeSelect wrapperClassName="w-44" value={form.proposed_risk_tier} onChange={(e) => setForm({ ...form, proposed_risk_tier: e.target.value })}>
                      {TIERS.map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                    </NativeSelect>
                  </label>
                </div>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Body</span>
                  <Textarea className="min-h-[320px] font-mono text-xs" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Change note</span>
                  <Input value={form.change_note} onChange={(e) => setForm({ ...form, change_note: e.target.value })} />
                </label>
              </section>
            </Card>
          ) : (
            <Card asChild>
              <section className="flex flex-col gap-3 p-5 text-sm">
                <h2 className="text-xs uppercase tracking-wider text-muted-foreground">
                  {draft.kind === "retire" ? "Retire this page" : draft.state === "published" ? "Published change" : "Compared with the current page"}
                </h2>
                {draft.change_note && <p>Ghi chú: {draft.change_note}</p>}
                {diff && draft.kind !== "retire" && (
                  <>
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">Title</div>
                      <DiffLines lines={diff.title_diff} />
                    </div>
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">Body</div>
                      <DiffLines lines={diff.body_diff} />
                    </div>
                  </>
                )}
              </section>
            </Card>
          )}

          {(showChunks || !editing) && diff && draft.kind !== "retire" && (
            <Card asChild>
              <section className="p-5 text-sm">
                <h2 className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">
                  Chunks on publish · {diff.chunks_preview.length}{editing ? " (saved version)" : ""}
                </h2>
                <ol className="flex flex-col gap-2">
                  {diff.chunks_preview.map((c, i) => (
                    <li key={i} className="rounded-md bg-muted p-2 text-xs">
                      {c.section_title && <div className="mb-1 font-medium">{c.section_title}</div>}
                      <div className="whitespace-pre-wrap">{c.content}</div>
                    </li>
                  ))}
                </ol>
              </section>
            </Card>
          )}

          {reviewing && (
            <Card asChild>
              <section className="flex flex-col gap-3 p-5 text-sm">
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Comment (required when asking for changes)</span>
                  <Input value={comment} onChange={(e) => setComment(e.target.value)} />
                </label>
                {draft.article?.auto_reply_allowed && draft.kind !== "create" && (
                  <Alert variant="warn" className="text-xs">
                    <AlertDescription>
                      On publish: version {draft.article.version} → {draft.article.version + 1}, the page is re-indexed,
                      its auto-reply authority is revoked (logged) and it joins the authority queue. Until a manager approves it
                      again, automatic answers citing this page go to a person.
                    </AlertDescription>
                  </Alert>
                )}
                <div className="flex justify-end gap-2">
                  <Button variant="outline"
                    onClick={() => void run(() => act("review", { decision: "request_changes", comment }), "Changes requested.")}
                  >
                    Request changes
                  </Button>
                  <Button onClick={() => void run(() => act("review", { decision: "approve", comment }), "Approved.")}>
                    {draft.kind === "retire" ? "Approve and retire" : "Approve and publish"}
                  </Button>
                </div>
              </section>
            </Card>
          )}
          {isAuthor && draft.state === "in_review" && (
            <p className="text-xs text-muted-foreground">Someone other than you must review your draft.</p>
          )}
        </div>

        <aside className="flex flex-col gap-4">
          {gap && (
            <Card asChild>
              <section className="p-4 text-sm">
                <h2 className="mb-1 font-medium">Started from a KB gap</h2>
                <p className="mb-2 text-xs text-muted-foreground">
                  {gap.label} · {gap.size} unanswered tickets
                </p>
                <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Sample tickets (masked)</div>
                <ul className="mt-1 flex flex-col gap-1 text-xs">
                  {gap.tickets.map((t) => (
                    <li key={t.public_id}>
                      <Link href={`/tickets/${t.public_id}`} className="text-primary">
                        {t.public_id}
                      </Link>{" "}
                      · {t.subject_masked}
                    </li>
                  ))}
                </ul>
              </section>
            </Card>
          )}
          {draft.article && (
            <Card asChild>
              <section className="p-4 text-xs">
                <h2 className="mb-2 text-sm font-medium">Current page</h2>
                <p>Version <span className="num">{draft.article.version}</span></p>
                <p>Risk: {draft.article.risk_tier}</p>
                <p>Auto-reply: {draft.article.auto_reply_allowed ? "allowed" : "not allowed"}</p>
                {draft.article.auto_reply_allowed && draft.kind !== "create" && editing && (
                  <Alert variant="warn" className="mt-2">
                    <AlertDescription>
                      Publishing this edit revokes the page's auto-reply authority until a manager approves the new text
                      (BR-F6-04).
                    </AlertDescription>
                  </Alert>
                )}
              </section>
            </Card>
          )}
        </aside>
      </div>
    </Page>
  );
}
