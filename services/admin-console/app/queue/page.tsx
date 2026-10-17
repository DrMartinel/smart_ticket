"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

// The review queue is now the "Needs review" view of the ticket list.
export default function QueueRedirect() {
  const router = useRouter();
  useEffect(() => router.replace("/tickets?view=review"), [router]);
  return null;
}
