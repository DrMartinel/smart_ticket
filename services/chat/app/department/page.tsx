"use client";

// My department's tickets (F14, BR-F14-11): what people in the departments a head heads have asked for, masked.

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Building2 } from "lucide-react";
import AppHeader from "@/components/AppHeader";
import { day } from "@/components/Rating";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/ui/states";
import { requesterApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import { DEPARTMENT_READ } from "@/lib/session";
import type { DepartmentTicketOut } from "@/lib/types/generated";

export default function DepartmentTicketsPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [rows, setRows] = useState<DepartmentTicketOut[] | null>(null);
  const [openOnly, setOpenOnly] = useState(true);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  const allowed = !!user?.permissions?.includes(DEPARTMENT_READ);

  const load = useCallback(() => {
    setError(false);
    setRows(null);
    requesterApi
      .departmentTickets(openOnly)
      .then(setRows)
      .catch(() => setError(true));
  }, [openOnly]);

  useEffect(() => {
    if (user && allowed) load();
  }, [user, allowed, load]);

  if (!user) return null;
  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <main id="main" className="flex-1">
        <Page width="form" className="flex flex-col gap-6 px-4 py-6 sm:px-6">
          <PageHeader
            eyebrow="Department"
            title="Department tickets"
            description="Tickets raised by people in the departments you head, and every department under them. You can read them here; support works them."
            actions={
              allowed && (
                <div className="flex gap-1">
                  <Button size="sm" variant={openOnly ? "default" : "outline"} onClick={() => setOpenOnly(true)}>
                    Open
                  </Button>
                  <Button size="sm" variant={openOnly ? "outline" : "default"} onClick={() => setOpenOnly(false)}>
                    All
                  </Button>
                </div>
              )
            }
          />
          {!allowed && (
            <EmptyState icon={Building2} title="You don't head a department">
              A department head sees their department's tickets here.
            </EmptyState>
          )}
          {allowed && error && <ErrorState title="Couldn't load your department's tickets." onRetry={load} />}
          {allowed && !rows && !error && <LoadingState rows={4} />}
          {allowed && rows && rows.length === 0 && <EmptyState title={openOnly ? "No open tickets" : "No tickets"} />}
          {allowed && rows && rows.length > 0 && (
            <Card className="divide-y divide-border">
              {rows.map((t) => (
                <div key={t.public_id} className="flex flex-wrap items-start justify-between gap-2 px-4 py-3">
                  <div className="min-w-0">
                    <p className="truncate font-medium">{t.subject_masked}</p>
                    <p className="text-xs text-muted-foreground">
                      <span className="font-mono">{t.public_id}</span> · {t.requester_name || t.requester}
                      {t.department ? ` · ${t.department}` : ""} · {day(t.created_at)}
                    </p>
                  </div>
                  <div className="text-right text-sm">
                    <span>{t.status_label}</span>
                    {t.team && <span className="block text-xs text-muted-foreground">{t.team}</span>}
                  </div>
                </div>
              ))}
            </Card>
          )}
        </Page>
      </main>
    </div>
  );
}
