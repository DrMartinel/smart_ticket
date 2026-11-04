"use client";

// The known issue a ticket is linked to (F7 · Incident banner 14-1332): title, latest update, ETA.

import { AlertTriangle, CheckCircle2 } from "lucide-react";
import type { IncidentBannerOut } from "@/lib/types/generated";

function hm(iso: string): string {
  return new Date(iso).toLocaleTimeString("en-GB", { timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit" });
}

export default function IncidentBanner({ incident, publicId }: { incident: IncidentBannerOut; publicId: string }) {
  const resolved = incident.status === "resolved";
  const eta = incident.eta_unknown ? "not known yet" : incident.eta ? hm(incident.eta) : null;
  const Icon = resolved ? CheckCircle2 : AlertTriangle;
  return (
    <section
      role="status"
      className={`flex gap-3 rounded-md border px-4 py-3 text-sm ${
        resolved ? "border-ok/25 bg-ok-soft" : "border-warn/25 bg-warn-soft"
      }`}
    >
      <Icon className={`mt-0.5 size-4 shrink-0 ${resolved ? "text-ok" : "text-warn"}`} aria-hidden />
      <div className="min-w-0">
        <p className={`font-semibold ${resolved ? "text-ok" : "text-warn"}`}>
          {resolved ? "Resolved" : "Known issue"}: {incident.title}
        </p>
        <p className="mt-1 text-foreground">
          {incident.last_update ?? "IT has the issue and is looking into it."}
          {!resolved && eta && ` Expected fix: ${eta}.`} Your ticket <span className="num">{publicId}</span> is linked, so
          there&apos;s no need to open another.
        </p>
        {incident.last_update_at && (
          <p className="mt-1 text-xs text-muted-foreground">
            Updated <span className="num">{hm(incident.last_update_at)}</span> · stage {incident.stage}
          </p>
        )}
      </div>
    </section>
  );
}
