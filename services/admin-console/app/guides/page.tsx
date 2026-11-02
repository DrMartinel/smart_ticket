"use client";

import { useAuth } from "@/lib/auth";
import { useTours } from "@/components/tour/TourProvider";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";

export default function GuidesPage() {
  const { user } = useAuth();
  const { tours, done, start } = useTours();
  const language = user?.language ?? "vi";

  return (
    <div className="mx-auto flex max-w-[860px] flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold">Hướng dẫn · Guides</h1>
        <p className="text-xs text-muted-foreground">
          {language === "vi"
            ? "Mỗi hướng dẫn đi từng bước qua một tính năng, ngay trên màn hình thật. Bạn chỉ thấy hướng dẫn cho những gì vai trò của bạn dùng được."
            : "Each guide walks through one feature, step by step, on the real screens. You only see guides for what your role can use."}
        </p>
      </header>

      <ul className="grid grid-cols-1 gap-3 md:grid-cols-2">
        {tours.map((tour) => (
          <Card asChild key={tour.id}>
            <li className="flex flex-col gap-2 p-4">
              <div className="flex items-start justify-between gap-3">
                <h2 className="text-sm font-semibold">{tour.title[language]}</h2>
                {done.includes(tour.id) && (
                  <Badge variant="ok">{language === "vi" ? "Đã xem" : "Done"}</Badge>
                )}
              </div>
              <p className="flex-1 text-sm text-muted-foreground">{tour.summary[language]}</p>
              <div className="flex items-center justify-between gap-3 pt-1">
                <span className="text-xs text-muted-foreground">
                  {tour.steps.length} {language === "vi" ? "bước" : tour.steps.length === 1 ? "step" : "steps"}
                </span>
                <Button size="sm" variant={done.includes(tour.id) ? "outline" : "default"} onClick={() => start(tour.id)}>
                  {done.includes(tour.id) ? (language === "vi" ? "Xem lại" : "Replay") : language === "vi" ? "Bắt đầu" : "Start"}
                </Button>
              </div>
            </li>
          </Card>
        ))}
      </ul>
    </div>
  );
}
