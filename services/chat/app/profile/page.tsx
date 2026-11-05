"use client";

// My profile (F14, FR-F14-014): who the help desk sees, where they sit and who they report to.

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import AppHeader from "@/components/AppHeader";
import { Card } from "@/components/ui/card";
import { Page, PageHeader } from "@/components/ui/page-header";
import { ErrorState, LoadingState } from "@/components/ui/states";
import { profileApi } from "@/lib/api";
import { useAuth } from "@/lib/auth";
import type { UserOut } from "@/lib/types/generated";

export default function ProfilePage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const [me, setMe] = useState<UserOut | null>(null);
  const [error, setError] = useState(false);

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  useEffect(() => {
    if (user) profileApi.me().then(setMe).catch(() => setError(true));
  }, [user]);

  if (!user) return null;
  const rows: [string, string][] = me
    ? [
        ["Name", me.name || "—"],
        ["Username", me.username],
        ["Email", me.email || "—"],
        ["Department", me.department ? `${me.department.name} (${me.department.code})` : "—"],
        ["Line manager", me.line_manager ?? "—"],
        ["Job title", me.job_title || "—"],
        ["Location", me.location || "—"],
      ]
    : [];
  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <main id="main" className="flex-1">
        <Page width="form" className="flex flex-col gap-6 px-4 py-6 sm:px-6">
          <PageHeader eyebrow="Account" title="My profile" description="Your company directory record. Ask IT to change anything that's wrong." />
          {error && <ErrorState title="Couldn't load your profile." />}
          {!me && !error && <LoadingState rows={4} />}
          {me && (
            <Card className="p-4 sm:p-5">
              <dl className="grid grid-cols-[130px_1fr] gap-x-4 gap-y-2 text-sm">
                {rows.map(([k, v]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd>{v}</dd>
                  </div>
                ))}
              </dl>
            </Card>
          )}
        </Page>
      </main>
    </div>
  );
}
