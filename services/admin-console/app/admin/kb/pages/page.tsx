"use client";

import { ArticleList } from "@/components/kb/ArticleList";
import { AuthorityTabs } from "@/components/kb/KbTabs";
import { useRequireAuth } from "@/lib/auth";

export default function AllPagesPage() {
  const user = useRequireAuth();
  if (!user) return null;
  return (
    <div className="mx-auto max-w-[1280px]">
      <AuthorityTabs user={user} />
      <ArticleList user={user} manage />
    </div>
  );
}
