"use client";

import { ArticleList } from "@/components/kb/ArticleList";
import { useRequireAuth } from "@/lib/auth";
import { SectionTabs } from "@/components/TabNav";

export default function AllPagesPage() {
  const user = useRequireAuth();
  if (!user) return null;
  return (
    <div className="mx-auto max-w-[1280px]">
      <SectionTabs />
      <ArticleList user={user} manage />
    </div>
  );
}
