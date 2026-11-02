"use client";

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
      .catch(() => setError("Không tải được bản nháp."));
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
        {error ? <Alert variant="danger" className="text-sm"><AlertDescription>{error}</AlertDescription></Alert> : <p className="text-sm text-muted-foreground">Đang tải…</p>}
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
      setError(err instanceof ApiError ? `${err.code ?? err.status}: ${err.message}` : "Thao tác thất bại.");
    }
  };

  const save = () => api.patch(`/api/kb/drafts/${id}`, form);
  const act = (action: string, body?: unknown) => api.post(`/api/kb/drafts/${id}/${action}`, body);

  return (
    <div className="mx-auto max-w-[1180px]">
      <KbTabs user={user} />
      <header className="mb-4 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold">
            {reviewing ? "Duyệt" : KIND_VI[draft.kind]} · <span className="font-mono">{draft.slug}</span>
          </h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
            <DraftStateChip state={draft.state} />
            <span>Tác giả {draft.author.username}</span>
            {draft.base_version !== null && <span>· dựa trên phiên bản {draft.base_version}</span>}
            <span>· rủi ro đề xuất {draft.proposed_risk_tier}</span>
            {draft.state !== "published" && <span>· không được truy xuất cho đến khi xuất bản (BR-F6-01)</span>}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {editing && (
            <>
              <Button variant="outline" onClick={() => void run(save, "Đã lưu.")}>
                Lưu
              </Button>
              <Button variant="outline" onClick={() => setShowChunks(!showChunks)}>
                Xem trước chunk
              </Button>
              <Button onClick={() => void run(async () => (await save(), act("submit")), "Đã gửi duyệt.")}>
                Gửi duyệt
              </Button>
            </>
          )}
          {isAuthor && draft.kind === "retire" && EDITABLE.includes(draft.state) && (
            <Button onClick={() => void run(() => act("submit"), "Đã gửi duyệt.")}>
              Gửi duyệt
            </Button>
          )}
          {isAuthor && draft.state === "conflict" && (
            <Button onClick={() => void run(() => act("rebase"), "Đã cập nhật theo trang hiện tại.")}>
              Cập nhật theo trang hiện tại (rebase)
            </Button>
          )}
          {(isAuthor || user.role === "manager") && [...EDITABLE, "conflict"].includes(draft.state) && (
            <Button variant="outline" onClick={() => void run(() => act("withdraw"), "Đã rút bản nháp.")}>
              Rút
            </Button>
          )}
        </div>
      </header>

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
            Trang đã thay đổi từ khi bản nháp bắt đầu. Tác giả cập nhật theo trang hiện tại rồi gửi duyệt lại.
          </AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_330px]">
        <div className="flex flex-col gap-4">
          {editing ? (
            <Card asChild>
              <section className="flex flex-col gap-3 p-5 text-sm">
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Tiêu đề · Title</span>
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
                    <span className="text-xs text-muted-foreground">Mức rủi ro đề xuất · Proposed risk tier</span>
                    <NativeSelect wrapperClassName="w-44" value={form.proposed_risk_tier} onChange={(e) => setForm({ ...form, proposed_risk_tier: e.target.value })}>
                      {TIERS.map((t) => (
                        <option key={t}>{t}</option>
                      ))}
                    </NativeSelect>
                  </label>
                </div>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Nội dung (Markdown) · Body</span>
                  <Textarea className="min-h-[320px] font-mono text-xs" value={form.body} onChange={(e) => setForm({ ...form, body: e.target.value })} />
                </label>
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">Ghi chú thay đổi · Change note</span>
                  <Input value={form.change_note} onChange={(e) => setForm({ ...form, change_note: e.target.value })} />
                </label>
              </section>
            </Card>
          ) : (
            <Card asChild>
              <section className="flex flex-col gap-3 p-5 text-sm">
                <h2 className="text-xs uppercase tracking-wider text-muted-foreground">
                  {draft.kind === "retire" ? "Gỡ trang này" : draft.state === "published" ? "Thay đổi đã xuất bản" : "So với trang hiện tại"}
                </h2>
                {draft.change_note && <p>Ghi chú: {draft.change_note}</p>}
                {diff && draft.kind !== "retire" && (
                  <>
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">Tiêu đề</div>
                      <DiffLines lines={diff.title_diff} />
                    </div>
                    <div>
                      <div className="mb-1 text-xs text-muted-foreground">Nội dung</div>
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
                  Chunk khi xuất bản · {diff.chunks_preview.length} chunks{editing ? " (bản đã lưu)" : ""}
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
                  <span className="text-xs text-muted-foreground">Nhận xét · Comment (bắt buộc khi yêu cầu sửa)</span>
                  <Input value={comment} onChange={(e) => setComment(e.target.value)} />
                </label>
                {draft.article?.auto_reply_allowed && draft.kind !== "create" && (
                  <Alert variant="warn" className="text-xs">
                    <AlertDescription>
                      Khi xuất bản: phiên bản {draft.article.version} → {draft.article.version + 1}, trang được nạp lại,
                      quyền trả lời tự động bị thu hồi (ghi kb_authority_log) và trang vào hàng chờ quyền. Đến khi được duyệt
                      lại, câu trả lời tự động trích trang này sẽ chuyển cho người (kb_not_authorized).
                    </AlertDescription>
                  </Alert>
                )}
                <div className="flex justify-end gap-2">
                  <Button variant="outline"
                    onClick={() => void run(() => act("review", { decision: "request_changes", comment }), "Đã yêu cầu sửa.")}
                  >
                    Yêu cầu sửa
                  </Button>
                  <Button onClick={() => void run(() => act("review", { decision: "approve", comment }), "Đã duyệt.")}>
                    {draft.kind === "retire" ? "Duyệt và gỡ trang" : "Duyệt và xuất bản"}
                  </Button>
                </div>
              </section>
            </Card>
          )}
          {isAuthor && draft.state === "in_review" && (
            <p className="text-xs text-muted-foreground">Một người khác phải duyệt bản nháp của bạn (BR-F6-02).</p>
          )}
        </div>

        <aside className="flex flex-col gap-4">
          {gap && (
            <Card asChild>
              <section className="p-4 text-sm">
                <h2 className="mb-1 font-medium">Bắt đầu từ cụm thiếu KB</h2>
                <p className="mb-2 text-xs text-muted-foreground">
                  {gap.label} · {gap.size} phiếu bị từ chối
                </p>
                <div className="text-[11px] uppercase tracking-wider text-muted-foreground">Phiếu mẫu (đã che)</div>
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
                <h2 className="mb-2 text-sm font-medium">Trang hiện tại</h2>
                <p>Phiên bản {draft.article.version}</p>
                <p>Rủi ro {draft.article.risk_tier}</p>
                <p>Trả lời tự động: {draft.article.auto_reply_allowed ? "được phép" : "không"}</p>
                {draft.article.auto_reply_allowed && draft.kind !== "create" && editing && (
                  <Alert variant="warn" className="mt-2">
                    <AlertDescription>
                      Xuất bản bản sửa sẽ thu hồi quyền trả lời tự động của trang này đến khi quản lý duyệt lại nội dung mới
                      (BR-F6-04).
                    </AlertDescription>
                  </Alert>
                )}
              </section>
            </Card>
          )}
        </aside>
      </div>
    </div>
  );
}
