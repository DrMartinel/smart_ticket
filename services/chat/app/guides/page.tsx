"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import AppHeader from "@/components/AppHeader";
import { useTours } from "@/components/tour/TourProvider";
import { useAuth } from "@/lib/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export default function GuidesPage() {
  const { user, loading } = useAuth();
  const router = useRouter();
  const { tours, done, start } = useTours();
  const language = user?.language ?? "vi";

  useEffect(() => {
    if (!loading && !user) router.replace("/login");
  }, [loading, user, router]);

  if (!user) return null;

  return (
    <div className="flex min-h-dvh flex-col">
      <AppHeader />
      <main className="mx-auto flex w-full max-w-3xl flex-col gap-4 px-4 py-6 md:px-6">
        <header>
          <h1 className="text-xl font-semibold">Hướng dẫn · Guides</h1>
          <p className="text-sm text-muted-foreground">
            {language === "vi"
              ? "Mỗi hướng dẫn đi từng bước qua một phần của IT Help, ngay trên màn hình thật."
              : "Each guide walks through one part of IT Help, step by step, on the real screens."}
          </p>
        </header>
        <ul className="flex flex-col gap-3">
          {tours.map((tour) => (
            <Card asChild key={tour.id}>
              <li className="flex flex-col gap-2 px-4 py-4">
                <div className="flex items-start justify-between gap-3">
                  <h2 className="font-medium">{tour.title[language]}</h2>
                  {done.includes(tour.id) && <Badge variant="ok">{language === "vi" ? "Đã xem" : "Done"}</Badge>}
                </div>
                <p className="text-sm text-muted-foreground">{tour.summary[language]}</p>
                <div className="flex items-center justify-between gap-3 pt-1">
                  <span className="text-xs text-muted-foreground">
                    {tour.steps.length} {language === "vi" ? "bước" : "steps"}
                  </span>
                  <Button size="sm" variant={done.includes(tour.id) ? "outline" : "default"} onClick={() => start(tour.id)}>
                    {done.includes(tour.id) ? (language === "vi" ? "Xem lại" : "Replay") : language === "vi" ? "Bắt đầu" : "Start"}
                  </Button>
                </div>
              </li>
            </Card>
          ))}
        </ul>
      </main>
    </div>
  );
}
