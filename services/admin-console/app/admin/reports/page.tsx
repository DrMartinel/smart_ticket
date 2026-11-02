"use client";

// /reports opens the first report the user may read.

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { reportTabs } from "@/components/reports/shared";
import { useRequireAuth } from "@/lib/auth";

export default function ReportsIndex() {
  const user = useRequireAuth();
  const router = useRouter();
  useEffect(() => {
    if (user) router.replace(`/admin/reports/${reportTabs(user)[0]?.key ?? "sla"}`);
  }, [user, router]);
  return null;
}
