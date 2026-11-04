"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";
import AppHeader from "@/components/AppHeader";
import { useTours } from "@/components/tour/TourProvider";
import { useAuth } from "@/lib/auth";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Page, PageHeader } from "@/components/ui/page-header";

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
      <main id="main" className="flex-1">
        <Page width="form" className="flex flex-col gap-5 px-4 py-6 sm:px-6">
          <PageHeader
            eyebrow="Help"
            vi="Hướng dẫn"
            title="Guides"
            description={
              language === "vi"
                ? "Mỗi hướng dẫn đi từng bước qua một phần của IT Help, ngay trên màn hình thật."
                : "Each guide walks through one part of IT Help, step by step, on the real screens."
            }
          />
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
                      <span className="num">{tour.steps.length}</span> {language === "vi" ? "bước" : "steps"}
                    </span>
                    <Button size="sm" variant={done.includes(tour.id) ? "outline" : "default"} onClick={() => start(tour.id)}>
                      {done.includes(tour.id) ? (language === "vi" ? "Xem lại" : "Replay") : language === "vi" ? "Bắt đầu" : "Start"}
                    </Button>
                  </div>
                </li>
              </Card>
            ))}
          </ul>
        </Page>
      </main>
    </div>
  );
}
