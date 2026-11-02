"use client";

// Start a KB draft (F6 UC-F6-01): a new page, an edit or a retirement, optionally from a gap.

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { KbTabs, KIND_VI } from "@/components/kb/KbTabs";
import { api, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { DraftOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";

const CATEGORIES = ["access", "network", "hardware", "software", "security", "other"];

export default function NewDraftPage() {
  const user = useRequireAuth();
  const router = useRouter();
  const search = useSearchParams();
  const kind = search.get("kind") ?? "create";
  const [slug, setSlug] = useState(search.get("slug") ?? "");
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("other");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (!user) return null;

  const start = async () => {
    setBusy(true);
    setError(null);
    try {
      const draft = await api.post<DraftOut>("/api/kb/drafts", {
        kind,
        slug: slug.trim(),
        // An edit or a retirement starts from the live page's text.
        ...(kind === "create" ? { title: title.trim(), body: `# ${title.trim()}\n\n`, category } : {}),
        change_note: note,
        gap_cluster_id: search.get("gap") || undefined,
      });
      router.push(`/kb/drafts/${draft.id}`);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không tạo được bản nháp.");
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-[760px]">
      <KbTabs user={user} />
      <h1 className="mb-4 text-xl font-semibold">{KIND_VI[kind] ?? kind} · New draft</h1>
      <Card asChild>
        <form
          className="flex flex-col gap-3 p-5 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            void start();
          }}
        >
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Slug</span>
            <Input className="font-mono" value={slug} onChange={(e) => setSlug(e.target.value)} readOnly={kind !== "create"} required />
          </label>
          {kind === "create" && (
            <>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Tiêu đề · Title</span>
                <Input value={title} onChange={(e) => setTitle(e.target.value)} required />
              </label>
              <label className="flex flex-col gap-1">
                <span className="text-xs text-muted-foreground">Category</span>
                <NativeSelect value={category} onChange={(e) => setCategory(e.target.value)}>
                  {CATEGORIES.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </NativeSelect>
              </label>
            </>
          )}
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Ghi chú thay đổi · Change note{kind === "retire" ? " (lý do gỡ)" : ""}</span>
            <Input value={note} onChange={(e) => setNote(e.target.value)} required={kind === "retire"} />
          </label>
          {search.get("gap") && <p className="text-xs text-muted-foreground">Bắt đầu từ một cụm thiếu KB; cụm sẽ được đánh dấu “drafted”.</p>}
          {error && <Alert variant="danger"><AlertDescription>{error}</AlertDescription></Alert>}
          <div className="flex justify-end">
            <Button type="submit" disabled={busy}>
              Tạo bản nháp
            </Button>
          </div>
        </form>
      </Card>
    </div>
  );
}
