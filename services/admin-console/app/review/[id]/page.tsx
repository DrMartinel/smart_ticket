"use client";

import { useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import { useRequireAuth } from "@/lib/auth";
import { api } from "@/lib/api";

// A review is done on its ticket's page now; old links land there.
export default function ReviewRedirect() {
  const user = useRequireAuth();
  const { id } = useParams<{ id: string }>();
  const router = useRouter();

  useEffect(() => {
    if (!user) return;
    api
      .get<{ ticket_public_id: string }>(`/api/review/items/${id}`)
      .then((item) => router.replace(`/tickets/${item.ticket_public_id}`))
      .catch(() => router.replace("/tickets?view=review"));
  }, [user, id, router]);

  return null;
}
