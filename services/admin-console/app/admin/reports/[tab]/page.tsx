"use client";

// The Reports section (F10): one tab per report, each gated like its endpoint.

import type { ReactNode } from "react";
import { useParams } from "next/navigation";
import {
  CsatReport,
  IncidentsReport,
  KbReport,
  NotificationsReport,
  ReviewersReport,
  RolloutReport,
  SecurityReport,
  SlaReport,
  TeamsReport,
} from "@/components/reports/ReportViews";
import { ReportTabs, reportTabs, type ReportTab } from "@/components/reports/shared";
import { useRequireAuth } from "@/lib/auth";

export default function ReportPage() {
  const tab = String(useParams().tab ?? "");
  const user = useRequireAuth();
  if (!user) return null;
  const allowed = reportTabs(user).map((t) => t.key);
  const active = (allowed.includes(tab as ReportTab) ? tab : allowed[0]) as ReportTab | undefined;
  if (!active) return <p className="text-sm text-muted-foreground">There are no reports for your role.</p>;
  const views: Record<ReportTab, ReactNode> = {
    sla: <SlaReport user={user} />,
    teams: <TeamsReport user={user} />,
    reviewers: <ReviewersReport />,
    kb: <KbReport />,
    csat: <CsatReport user={user} />,
    rollout: <RolloutReport />,
    security: <SecurityReport />,
    incidents: <IncidentsReport />,
    notifications: <NotificationsReport />,
  };
  return (
    <div className="mx-auto max-w-[1180px]">
      <ReportTabs user={user} active={active} />
      {views[active]}
    </div>
  );
}
