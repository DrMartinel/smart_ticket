"use client";

// The reviewer's inbox (F14): the grants waiting for this person's keep or revoke.

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { useToast } from "@/components/ui/toast";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";
import type { ReviewItemOut } from "@/lib/types/generated";

export default function ReviewInboxPage() {
  const user = useRequireAuth();
  const toast = useToast();
  const [items, setItems] = useState<ReviewItemOut[] | null>(null);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setItems(await api.get<ReviewItemOut[]>("/api/access/reviews/inbox"));
      setError(null);
    } catch {
      setError("Couldn't load your access reviews.");
    }
  }, []);

  useEffect(() => {
    if (user) void load();
  }, [user, load]);

  if (!user) return null;

  const decide = async (item: ReviewItemOut, decision: "keep" | "revoke") => {
    try {
      await api.post(`/api/access/reviews/items/${item.id}/decide`, { decision, note: notes[item.id] ?? "" });
      toast.success(decision === "keep" ? `Kept ${item.user}'s ${item.role_name}` : `Revoked ${item.user}'s ${item.role_name}`);
      setItems((current) => current?.filter((i) => i.id !== item.id) ?? null);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : "Couldn't record the answer.");
    }
  };

  return (
    <Page width="form" className="flex flex-col gap-4">
      <PageHeader
        eyebrow="Workspace / Me"
        title="Access reviews"
        description="Does each person still need this access? Keep it, or revoke it now. A revoke ends the grant and signs them out."
      />
      {error && <ErrorState title={error} onRetry={() => void load()} />}
      {!items && !error && <LoadingState rows={3} />}
      {items && items.length === 0 && <EmptyState title="Nothing to review">When an access review sends you grants, they show here.</EmptyState>}
      {items?.map((item) => (
        <Card key={item.id} className="flex flex-col gap-3 p-4">
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div>
              <p className="font-medium">
                {item.user_name || item.user} <span className="text-muted-foreground">({item.user})</span>
              </p>
              <p className="text-sm">
                {item.role_name} <span className="text-muted-foreground">at {item.scope}</span>
              </p>
              <p className="text-xs text-muted-foreground">
                Granted {formatDate(item.granted_at)}
                {item.granted_by ? ` by ${item.granted_by}` : ""} · {item.campaign_name}, closes {formatDate(item.closes_at)}
              </p>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Input
              className="min-w-[200px] flex-1"
              placeholder="Note (optional)"
              value={notes[item.id] ?? ""}
              onChange={(e) => setNotes({ ...notes, [item.id]: e.target.value })}
            />
            <Button variant="outline" onClick={() => void decide(item, "keep")}>
              Keep
            </Button>
            <Button variant="destructive" onClick={() => void decide(item, "revoke")}>
              Revoke
            </Button>
          </div>
        </Card>
      ))}
    </Page>
  );
}
