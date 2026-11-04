"use client";

import { Labeled } from "@/components/Modal";
import { Page, PageHeader } from "@/components/ui/page-header";
import { ErrorState } from "@/components/ui/states";

// Start a KB draft (F6 UC-F6-01): a new page, an edit or a retirement, optionally from a gap.

import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";
import { KbTabs } from "@/components/kb/KbTabs";
import { api, ApiError } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { DraftOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

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
  const [tried, setTried] = useState(false);

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
      setError(err instanceof ApiError ? err.message : "Couldn't create the draft. Try again.");
      setBusy(false);
    }
  };

  return (
    <Page width="form">
      <KbTabs user={user} />
      <PageHeader
        className="mb-4"
        eyebrow="Knowledge / New draft"
        back={{ href: "/kb/drafts", label: "Drafts" }}
        title={kind === "create" ? "New help page" : kind === "retire" ? "Retire a help page" : "Edit a help page"}
        description="This starts a draft. Nothing changes for automatic answers until someone else reviews and publishes it."
      />
      <Card asChild>
        <form
          noValidate
          className="flex flex-col gap-4 p-5 text-sm"
          onSubmit={(e) => {
            e.preventDefault();
            setTried(true);
            if (!slug.trim() || (kind === "create" && !title.trim()) || (kind === "retire" && !note.trim())) return;
            void start();
          }}
        >
          <Labeled
            label="Slug"
            required
            hint={kind === "create" ? "Lowercase words joined by dots or dashes, e.g. vpn.reset-client." : "The page this draft changes."}
            error={tried && !slug.trim() ? "Give the page a slug." : null}
          >
            <Input className="num" value={slug} aria-invalid={tried && !slug.trim()} onChange={(e) => setSlug(e.target.value)} readOnly={kind !== "create"} />
          </Labeled>
          {kind === "create" && (
            <>
              <Labeled label="Title" required error={tried && !title.trim() ? "Give the page a title." : null}>
                <Input value={title} aria-invalid={tried && !title.trim()} onChange={(e) => setTitle(e.target.value)} />
              </Labeled>
              <Labeled label="Category">
                <NativeSelect value={category} onChange={(e) => setCategory(e.target.value)}>
                  {CATEGORIES.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </NativeSelect>
              </Labeled>
            </>
          )}
          <Labeled
            label={kind === "retire" ? "Why it's being retired" : "Change note"}
            required={kind === "retire"}
            hint="Reviewers see this next to the change."
            error={tried && kind === "retire" && !note.trim() ? "Say why the page is being retired." : null}
          >
            <Input value={note} onChange={(e) => setNote(e.target.value)} />
          </Labeled>
          {search.get("gap") && <p className="text-xs text-muted-foreground">Started from a KB gap; the gap will be marked as drafted.</p>}
          {error && <ErrorState compact title="The draft wasn't created">{error}</ErrorState>}
          <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
            <Button type="button" variant="outline" onClick={() => router.back()}>
              Cancel
            </Button>
            <Button type="submit" disabled={busy}>
              {busy ? "Creating…" : "Create draft"}
            </Button>
          </div>
        </form>
      </Card>
    </Page>
  );
}
