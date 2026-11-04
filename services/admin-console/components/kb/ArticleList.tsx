"use client";

import { Plus, SearchX } from "lucide-react";
import { PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState, TableStatus } from "@/components/ui/states";

// The help pages list: the Workspace shows it with editors' links, Admin with the manager's allow/revoke toggle.

import Link from "next/link";
import { Fragment, useEffect, useState } from "react";
import { canEditKb } from "@/lib/areas";
import type { CurrentUser } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { riskTierTone } from "@/lib/badges";
import { Button } from "@/components/ui/button";
import { NativeSelect } from "@/components/ui/native-select";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";

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

export function ArticleList({ user, manage }: { user: CurrentUser; manage: boolean }) {
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
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, category, offset]);

  const isManager = manage && user.role === "manager";
  const isEditor = !manage && canEditKb(user);

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
    <>
      <PageHeader
        className="mb-4"
        eyebrow={manage ? "Admin / Help pages" : "Knowledge / Help pages"}
        title={manage ? "All help pages" : "Help pages"}
        description={
          manage
            ? "Only pages allowed here can be used for automatic answers. Changing that needs a reason, and every change is logged. The AI can never grant it."
            : "Only pages marked Allowed can be used for automatic answers. Managers change which ones, in Admin."
        }
        actions={
          isEditor && (
            <Button asChild>
              <Link href="/kb/drafts/new">
                <Plus aria-hidden /> New page
              </Link>
            </Button>
          )
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          type="search"
          className="min-w-0 basis-full sm:max-w-md sm:basis-auto sm:flex-1"
          placeholder="Search by title or slug"
          aria-label="Search help pages"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOffset(0);
          }}
        />
        <NativeSelect wrapperClassName="w-full sm:w-48"
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
        <span className="num ml-auto text-xs text-muted-foreground">
          {count === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, count)}`} of {count}
        </span>
        <Button variant="outline" size="sm" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}>
          Previous
        </Button>
        <Button variant="outline" size="sm" disabled={offset + PAGE_SIZE >= count} onClick={() => setOffset(offset + PAGE_SIZE)}>
          Next
        </Button>
      </div>

      {error && <ErrorState className="mb-3" title={error} onRetry={() => load()} />}
      {articles === null && !error && (
        <Card className="px-4 py-3">
          <LoadingState rows={6} label="Loading help pages" />
        </Card>
      )}

      {articles && (
        <Card className="overflow-x-auto">
          <Table className="min-w-[720px] table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead>Page</TableHead>
                <TableHead className="w-32">Category</TableHead>
                <TableHead className="w-28">Risk</TableHead>
                <TableHead className="w-44">Automatic answers</TableHead>
                <TableHead className="w-44" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {articles.map((a) => (
                <Fragment key={a.slug}>
                  <TableRow className="align-top">
                    <TableCell className="py-3">
                      {a.source_url ? (
                        <a href={a.source_url} target="_blank" rel="noopener noreferrer" className="block truncate font-medium hover:text-primary">
                          {a.title}
                        </a>
                      ) : (
                        <span className="block truncate font-medium">{a.title}</span>
                      )}
                      <span className="num block truncate text-xs text-muted-foreground">{a.slug}</span>
                    </TableCell>
                    <TableCell className="py-3">{a.category}</TableCell>
                    <TableCell className="py-3">
                      <Badge variant={riskTierTone(a.risk_tier)}>{a.risk_tier}</Badge>
                    </TableCell>
                    <TableCell className="py-3">
                      {a.auto_reply_allowed ? <Badge variant="ok">Allowed</Badge> : <span className="text-muted-foreground">Not allowed</span>}
                    </TableCell>
                    <TableCell className="py-3 text-right">
                      {isEditor && (
                        <span className="mr-2 inline-flex gap-2 text-xs">
                          <Link href={`/kb/graph/${encodeURIComponent(a.slug)}`} className="text-primary hover:underline">
                            Graph
                          </Link>
                          <Link href={`/kb/drafts/new?kind=edit&slug=${encodeURIComponent(a.slug)}`} className="text-primary hover:underline">
                            Edit
                          </Link>
                          <Link href={`/kb/drafts/new?kind=retire&slug=${encodeURIComponent(a.slug)}`} className="text-danger hover:underline">
                            Retire
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
                          className="flex flex-wrap items-center gap-2"
                          onSubmit={(e) => {
                            e.preventDefault();
                            void toggle(a);
                          }}
                        >
                          <Input
                            aria-label="Reason (required, logged)"
                            className="min-w-0 flex-1 basis-full sm:basis-auto"
                            placeholder={`Why ${a.auto_reply_allowed ? "revoke" : "allow"} automatic answers from this page? (required, logged)`}
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            autoFocus
                          />
                          <Button type="submit" disabled={!reason.trim()} variant={a.auto_reply_allowed ? "destructive" : "default"}>
                            {a.auto_reply_allowed ? "Revoke automatic answers" : "Allow automatic answers"}
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
              <TableStatus
                colSpan={5}
                rows={articles}
                empty={
                  <EmptyState compact icon={SearchX} title={query || category ? "No help pages match" : "No help pages yet"}>
                    {query || category ? "Try another word from the title, or clear the category." : "Load the knowledge base, or write a page with New page."}
                  </EmptyState>
                }
              />
            </TableBody>
          </Table>
        </Card>
      )}
    </>
  );
}
