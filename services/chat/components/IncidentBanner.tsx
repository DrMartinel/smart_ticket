"use client";

// The known issue a ticket is linked to (F7 · Incident banner 14-1332): title, latest update, ETA.

import type { IncidentBannerOut } from "@/lib/types/generated";

function hm(iso: string): string {
  return new Date(iso).toLocaleTimeString("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit" });
}

export default function IncidentBanner({ incident, publicId }: { incident: IncidentBannerOut; publicId: string }) {
  const resolved = incident.status === "resolved";
  const eta = incident.eta_unknown ? "chưa xác định" : incident.eta ? hm(incident.eta) : null;
  return (
    <section
      role="status"
      className={`rounded-lg px-4 py-3 text-sm ${
        resolved ? "bg-ok-soft text-ok" : "bg-warn-soft text-warn"
      }`}
    >
      <p className="font-semibold">
        {resolved ? "✓ Sự cố đã khắc phục · Resolved" : "⚠ Sự cố đang xử lý · Known issue"}: {incident.title}
      </p>
      <p className="mt-1 text-foreground">
        {incident.last_update ?? "Đội IT đã nhận sự cố và đang kiểm tra."}
        {!resolved && eta && ` Dự kiến: ${eta}.`} Your ticket {publicId} is linked — no need to open another.
      </p>
      {incident.last_update_at && (
        <p className="mt-1 text-xs text-muted-foreground">
          Cập nhật {hm(incident.last_update_at)} · stage {incident.stage}
        </p>
      )}
    </section>
  );
}
