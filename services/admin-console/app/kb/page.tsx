"use client";

import { Fragment, useEffect, useState } from "react";
import { useRequireAuth } from "@/lib/auth";
import { api, ApiError } from "@/lib/api";
import { riskTierClasses } from "@/lib/badges";

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
      <header className="mb-5">
        <h1 className="text-2xl font-semibold tracking-tight">Help pages</h1>
        <p className="mt-0.5 max-w-2xl text-sm text-[var(--text-muted)]">
          {isManager
            ? "Only pages allowed here can be used for automatic answers. Changing that needs a reason, and every change is logged. The AI can never grant it."
            : "Only pages allowed here can be used for automatic answers. Managers change which ones."}
        </p>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          className="field min-w-0 max-w-md flex-1"
          placeholder="Search by title or slug"
          aria-label="Search help pages"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOffset(0);
          }}
        />
        <select
          className="field w-48"
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
        </select>
        <span className="ml-auto text-sm text-[var(--text-muted)]">
          {count === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, count)}`} of {count}
        </span>
        <button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))} className="btn btn-secondary py-1">
          Previous
        </button>
        <button disabled={offset + PAGE_SIZE >= count} onClick={() => setOffset(offset + PAGE_SIZE)} className="btn btn-secondary py-1">
          Next
        </button>
      </div>

      {error && <p className="tone-danger mb-3 rounded-[5px] px-3 py-2 text-sm">{error}</p>}
      {articles === null && !error && <p className="text-sm text-[var(--text-muted)]">Loading…</p>}

      {articles && (
        <div className="card overflow-x-auto">
          <table className="w-full min-w-[720px] table-fixed text-sm">
            <thead className="bg-[var(--surface-2)] text-left text-xs text-[var(--text-muted)]">
              <tr>
                <th className="px-4 py-2.5 font-medium">Page</th>
                <th className="w-32 px-4 py-2.5 font-medium">Category</th>
                <th className="w-28 px-4 py-2.5 font-medium">Risk</th>
                <th className="w-44 px-4 py-2.5 font-medium">Automatic answers</th>
                <th className="w-28 px-4 py-2.5" />
              </tr>
            </thead>
            <tbody>
              {articles.map((a) => (
                <Fragment key={a.slug}>
                  <tr className="border-t border-[var(--border)] align-top">
                    <td className="px-4 py-3">
                      {a.source_url ? (
                        <a href={a.source_url} target="_blank" rel="noopener noreferrer" className="block truncate font-medium hover:text-[var(--accent)]">
                          {a.title}
                        </a>
                      ) : (
                        <span className="block truncate font-medium">{a.title}</span>
                      )}
                      <span className="block truncate font-mono text-xs text-[var(--text-muted)]">{a.slug}</span>
                    </td>
                    <td className="px-4 py-3">{a.category}</td>
                    <td className="px-4 py-3">
                      <span className={`badge ${riskTierClasses(a.risk_tier)}`}>{a.risk_tier}</span>
                    </td>
                    <td className="px-4 py-3">
                      {a.auto_reply_allowed ? <span className="badge tone-ok">Allowed</span> : <span className="text-[var(--text-muted)]">Not allowed</span>}
                    </td>
                    <td className="px-4 py-3 text-right">
                      {isManager && (
                        <button onClick={() => setPendingSlug(pendingSlug === a.slug ? null : a.slug)} className="btn btn-secondary py-1 text-xs">
                          {a.auto_reply_allowed ? "Revoke" : "Allow"}
                        </button>
                      )}
                    </td>
                  </tr>
                  {pendingSlug === a.slug && (
                    <tr className="bg-[var(--surface-2)]">
                      <td colSpan={5} className="px-4 py-3">
                        <form
                          className="flex items-center gap-2"
                          onSubmit={(e) => {
                            e.preventDefault();
                            void toggle(a);
                          }}
                        >
                          <input
                            className="field flex-1"
                            placeholder={`Why ${a.auto_reply_allowed ? "revoke" : "allow"} automatic answers from this page? (required, logged)`}
                            value={reason}
                            onChange={(e) => setReason(e.target.value)}
                            autoFocus
                          />
                          <button type="submit" className="btn btn-primary">
                            Confirm
                          </button>
                          <button type="button" className="btn btn-secondary" onClick={() => setPendingSlug(null)}>
                            Cancel
                          </button>
                        </form>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
