"use client";

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import { KbTabs, canEditKb } from "@/components/kb/KbTabs";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { riskTierTone } from "@/lib/badges";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription } from "@/components/ui/alert";

interface KbArticle {
  id: string;
  slug: string;
  title: string;
  category: string;
  source_url: string;
  auto_reply_allowed: boolean;
  risk_tier: string;
  approved_by: string | null;
  is_active: boolean;
  version: number;
}

interface ArticlePage {
  items: KbArticle[];
  count: number;
}

const PAGE_SIZE = 50;
const CATEGORIES = ["", "access", "network", "hardware", "software", "security", "other"];

/**
 * Auto-reply authority lives here, on the KB article, not on anything the
 * LLM proposes (ADR-0002) — this page is the only place that flag can be
 * changed, and it always requires a reason, logged to kb_authority_log.
 */
export default function KbPage() {
  const user = useRequireAuth();
  const [articles, setArticles] = useState<KbArticle[] | null>(null);
  const [count, setCount] = useState(0);
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("");
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [pendingSlug, setPendingSlug] = useState<string | null>(null);
  const [reason, setReason] = useState("");

  const load = () => {
    const params = new URLSearchParams({ limit: String(PAGE_SIZE), offset: String(offset) });
    if (query.trim()) params.set("q", query.trim());
    if (category) params.set("category", category);
    api
      .get<ArticlePage>(`/api/kb?${params}`)
      .then((page) => {
        setArticles(page.items);
        setCount(page.count);
      })
      .catch(() => setError("Failed to load the knowledge base."));
  };

  useEffect(() => {
    if (user) load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, query, category, offset]);

  if (!user) return null;

  const isManager = user.role === "manager";
  const isEditor = canEditKb(user);

  const toggle = async (article: KbArticle) => {
    if (!reason.trim()) {
      setError("A reason is required to change auto-reply authority.");
      return;
    }
    setError(null);
    try {
      await api.post(`/api/kb/${article.slug}/auto-reply-allowed`, {
        allowed: !article.auto_reply_allowed,
        reason: reason.trim(),
      });
      setPendingSlug(null);
      setReason("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Failed to update this article.");
    }
  };

  return (
    <div className="mx-auto max-w-[1280px]">
      <KbTabs user={user} />
      <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
        <div>
        <h1 className="text-2xl font-semibold tracking-tight">Help pages</h1>
        <p className="mt-0.5 max-w-2xl text-sm text-muted-foreground">
          {isManager
            ? "Only pages allowed here can be used for automatic answers. Changing that needs a reason, and every change is logged. The AI can never grant it."
            : "Only pages allowed here can be used for automatic answers. Managers change which ones."}
        </p>
        </div>
        {isEditor && (
          <Button asChild>
            <Link href="/kb/drafts/new">
              Trang mới · New page
            </Link>
          </Button>
        )}
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          className="min-w-0 max-w-md flex-1"
          placeholder="Search by title or slug"
          aria-label="Search help pages"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOffset(0);
          }}
        />
        <NativeSelect wrapperClassName="w-48"
          aria-label="Category"
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setOffset(0);
          }}
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c || "All categories"}
            </option>
          ))}
        </NativeSelect>
        <span className="ml-auto text-sm text-muted-foreground">
          {count === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, count)}`} of {count}
        </span>
        <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          Previous
        </Button>
        <Button variant="outline" size="sm" disabled={offset + PAGE_SIZE >= count} onClick={() => setOffset(offset + PAGE_SIZE)}>
          Next
        </Button>
      </div>

      {error && <Alert variant="danger" className="mb-3 text-sm"><AlertDescription>{error}</AlertDescription></Alert>}
      {articles === null && !error && <p className="text-sm text-muted-foreground">Loading…</p>}

      {articles && (
        <Card className="overflow-x-auto">
          <Table className="w-full min-w-[720px] table-fixed text-sm">
            <TableHeader className="bg-muted text-left text-xs text-muted-foreground">
              <TableRow>
                <TableHead className="px-4 py-2.5 font-medium">Page</TableHead>
                <TableHead className="w-32 px-4 py-2.5 font-medium">Category</TableHead>
                <TableHead className="w-28 px-4 py-2.5 font-medium">Risk</TableHead>
                <TableHead className="w-44 px-4 py-2.5 font-medium">Automatic answers</TableHead>
                <TableHead className="w-44 px-4 py-2.5" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {articles.map((a) => (
                <Fragment key={a.slug}>
                  <TableRow className="border-t border-border align-top">
                    <TableCell className="px-4 py-3">
                      {a.source_url ? (
                        <a href={a.source_url} target="_blank" rel="noopener noreferrer" className="block truncate font-medium hover:text-primary">
                          {a.title}
                        </a>
                      ) : (
                        <span className="block truncate font-medium">{a.title}</span>
                      )}
                      <span className="block truncate font-mono text-xs text-muted-foreground">{a.slug}</span>
                    </TableCell>
                    <TableCell className="px-4 py-3">{a.category}</TableCell>
                    <TableCell className="px-4 py-3">
                      <Badge variant={riskTierTone(a.risk_tier)}>{a.risk_tier}</Badge>
                    </TableCell>
                    <TableCell className="px-4 py-3">
                      {a.auto_reply_allowed ? <Badge variant="ok">Allowed</Badge> : <span className="text-muted-foreground">Not allowed</span>}
                    </TableCell>
                    <TableCell className="px-4 py-3 text-right">
                      {isEditor && (
                        <span className="mr-2 inline-flex gap-2 text-xs">
                          <Link href={`/kb/graph/${encodeURIComponent(a.slug)}`} className="text-primary hover:underline">
                            Đồ thị
                          </Link>
                          <Link href={`/kb/drafts/new?kind=edit&slug=${encodeURIComponent(a.slug)}`} className="text-primary hover:underline">
                            Sửa
                          </Link>
                          <Link href={`/kb/drafts/new?kind=retire&slug=${encodeURIComponent(a.slug)}`} className="text-danger hover:underline">
                            Gỡ
                          </Link>
                        </span>
                      )}
                      {isManager && (
                        <Button variant="outline" size="xs" onClick={() => setPendingSlug(pendingSlug === a.slug ? null : a.slug)}>
                          {a.auto_reply_allowed ? "Revoke" : "Allow"}
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                  {pendingSlug === a.slug && (
                    <TableRow className="bg-muted">
                      <TableCell colSpan={5} className="px-4 py-3">
                        <form
                          className="flex items-center gap-2"
                          onSubmit={(e) => {
                            e.preventDefault();
                            void toggle(a);
                          }}
                        >
                          <Input
                            className="flex-1"
                            placeholder={`Why ${a.auto_reply_allowed ? "revoke" : "allow"} automatic answers from this page? (required, logged)`}
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            autoFocus
                          />
                          <Button type="submit">
                            Confirm
                          </Button>
                          <Button variant="outline" type="button" onClick={() => setPendingSlug(null)}>
                            Cancel
                          </Button>
                        </form>
                      </TableCell>
                    </TableRow>
                  )}
                </Fragment>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}
    </div>
  );
}
