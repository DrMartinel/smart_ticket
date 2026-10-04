"use client";

import { useEffect, useState } from "react";
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
    <div>
      <h1 className="mb-1 text-xl font-semibold">Knowledge base</h1>
      <p className="mb-6 text-sm text-[var(--text-muted)]">
        {isManager
          ? "Toggling auto-reply requires a reason and is logged (kb_authority_log). The model can never grant itself this authority."
          : "Only manager-role users can change auto-reply authority."}
      </p>

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <input
          className="min-w-0 flex-1 rounded border px-2 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", background: "var(--bg)" }}
          placeholder="Search slug or title"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setOffset(0);
          }}
        />
        <select
          className="rounded border px-2 py-1.5 text-sm"
          style={{ borderColor: "var(--border)", background: "var(--bg)" }}
          value={category}
          onChange={(e) => {
            setCategory(e.target.value);
            setOffset(0);
          }}
        >
          {CATEGORIES.map((c) => (
            <option key={c} value={c}>
              {c || "all categories"}
            </option>
          ))}
        </select>
        <span className="text-xs text-[var(--text-muted)]">
          {count === 0 ? "0" : `${offset + 1}–${Math.min(offset + PAGE_SIZE, count)}`} of {count}
        </span>
        <button
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          className="rounded border px-2 py-1.5 text-xs disabled:opacity-50"
          style={{ borderColor: "var(--border)" }}
        >
          Prev
        </button>
        <button
          disabled={offset + PAGE_SIZE >= count}
          onClick={() => setOffset(offset + PAGE_SIZE)}
          className="rounded border px-2 py-1.5 text-xs disabled:opacity-50"
          style={{ borderColor: "var(--border)" }}
        >
          Next
        </button>
      </div>

      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
      {articles === null && !error && <p className="text-sm text-[var(--text-muted)]">Loading…</p>}

      <div className="flex flex-col gap-2">
        {articles?.map((a) => (
          <div key={a.slug} className="card p-4">
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="text-sm font-medium">
                  {a.slug} — {a.title}
                </div>
                {a.source_url && (
                  <a
                    href={a.source_url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-[var(--accent)] underline"
                  >
                    source
                  </a>
                )}
                <div className="mt-1 flex flex-wrap gap-1.5">
                  <span className="badge bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300">{a.category}</span>
                  <span className={`badge ${riskTierClasses(a.risk_tier)}`}>risk: {a.risk_tier}</span>
                  <span
                    className={`badge ${a.auto_reply_allowed ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/40 dark:text-emerald-300" : "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"}`}
                  >
                    {a.auto_reply_allowed ? "auto-reply allowed" : "auto-reply not allowed"}
                  </span>
                </div>
              </div>
              {isManager && (
                <button
                  onClick={() => setPendingSlug(pendingSlug === a.slug ? null : a.slug)}
                  className="shrink-0 rounded border px-3 py-1.5 text-xs"
                  style={{ borderColor: "var(--border)" }}
                >
                  {a.auto_reply_allowed ? "Revoke" : "Allow"}
                </button>
              )}
            </div>

            {pendingSlug === a.slug && (
              <div className="mt-3 flex items-center gap-2 border-t pt-3" style={{ borderColor: "var(--border)" }}>
                <input
                  className="flex-1 rounded border px-2 py-1.5 text-sm"
                  style={{ borderColor: "var(--border)", background: "var(--bg)" }}
                  placeholder="Reason for this change (required, logged)"
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  autoFocus
                />
                <button
                  onClick={() => toggle(a)}
                  className="rounded bg-[var(--accent)] px-3 py-1.5 text-xs font-medium text-white"
                >
                  Confirm
                </button>
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
