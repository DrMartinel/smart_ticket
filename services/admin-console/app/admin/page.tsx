"use client";

// /admin opens the first Admin page the user may open, or the Workspace when there is none.

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { firstAdminPage } from "@/lib/areas";
import { useRequireAuth } from "@/lib/auth";

export default function AdminIndex() {
  const user = useRequireAuth();
  const router = useRouter();
  useEffect(() => {
    if (user) router.replace(firstAdminPage(user) ?? "/tickets?view=review");
  }, [user, router]);
  return null;
}
