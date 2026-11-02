"use client";

import { ArticleList } from "@/components/kb/ArticleList";
import { KbTabs } from "@/components/kb/KbTabs";
import { useRequireAuth } from "@/lib/auth";

export default function KbPage() {
  const user = useRequireAuth();
  if (!user) return null;
  return (
    <div className="mx-auto max-w-[1280px]">
      <KbTabs user={user} />
      <ArticleList user={user} manage={false} />
    </div>
  );
}
