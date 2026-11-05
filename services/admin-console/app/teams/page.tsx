"use client";

// Opens the first team the user can see.

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Users } from "lucide-react";
import { useVisibleTeamsState } from "@/components/TeamPicker";
import { useRequireAuth } from "@/lib/auth";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, LoadingState } from "@/components/ui/states";
import { P, can } from "@/lib/permissions";

export default function TeamsIndexPage() {
  const user = useRequireAuth();
  const router = useRouter();
  const { teams, loaded } = useVisibleTeamsState(user);

  useEffect(() => {
    if (teams.length > 0) router.replace(`/teams/${teams[0].slug}`);
  }, [teams, router]);

  if (!user) return null;
  return (
    <Page>
      <PageHeader eyebrow="Workspace / Teams" title="Team queues" description="Each team's open tickets, unassigned first." />
      <Card>
        {!loaded || teams.length > 0 ? (
          <div className="p-4">
            <LoadingState rows={4} label="Opening your team" />
          </div>
        ) : (
          <EmptyState
            icon={Users}
            title={can(user, P.teamsManage) ? "There are no teams yet" : "You're not in a team yet"}
            action={
              can(user, P.teamsManage) && (
                <Button asChild>
                  <Link href="/admin/settings/teams">Set up teams</Link>
                </Button>
              )
            }
          >
            {can(user, P.teamsManage)
              ? "Create a team and give it categories; tickets in those categories go to its queue."
              : "Ask a manager or your team lead to add you to a team."}
          </EmptyState>
        )}
      </Card>
    </Page>
  );
}
