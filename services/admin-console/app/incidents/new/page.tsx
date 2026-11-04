"use client";

// Declare an incident by hand (F7 · Declare incident 14-1298): confirmed at once, with a first
// broadcast and the tickets already known.

import { useRouter } from "next/navigation";
import { useState } from "react";
import { STAGES, fromLocal } from "@/components/incidents/chips";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import type { IncidentDetailOut } from "@/lib/types/generated";
import { Card } from "@/components/ui/card";
import { NativeSelect } from "@/components/ui/native-select";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Checkbox } from "@/components/ui/checkbox";
import { Labeled } from "@/components/Modal";
import { Page, PageHeader } from "@/components/ui/page-header";
import { Panel } from "@/components/ui/panel";
import { EmptyState, ErrorState } from "@/components/ui/states";
import { ShieldOff } from "lucide-react";

const CATEGORIES = ["network", "access", "hardware", "software", "security", "other"];

export default function DeclareIncidentPage() {
  const user = useRequireAuth();
  const router = useRouter();
  const [title, setTitle] = useState("");
  const [category, setCategory] = useState("network");
  const [service, setService] = useState("");
  const [tickets, setTickets] = useState("");
  const [stage, setStage] = useState("investigating");
  const [bodyVi, setBodyVi] = useState("");
  const [bodyEn, setBodyEn] = useState("");
  const [etaAt, setEtaAt] = useState("");
  const [etaUnknown, setEtaUnknown] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tried, setTried] = useState(false);

  if (!user) return null;
  if (!user.capabilities?.includes("incident_manager")) {
    return (
      <Page width="form">
        <PageHeader eyebrow="Workspace / Incidents" vi="Khai báo sự cố" title="Declare an incident" back={{ href: "/incidents", label: "Incidents" }} />
        <EmptyState icon={ShieldOff} title="Only incident managers can declare an incident">
          Ask a manager to give you the incident manager capability, or report what you see on an existing ticket.
        </EmptyState>
      </Page>
    );
  }

  const titleError = tried && title.trim().length < 3 ? "Give the incident a name of at least 3 characters." : null;

  async function declare() {
    setTried(true);
    if (title.trim().length < 3) return;
    setBusy(true);
    setError(null);
    try {
      const made = await api.post<IncidentDetailOut>("/api/incidents", {
        title,
        category,
        service,
        ticket_ids: tickets.split(/[\s,]+/).filter(Boolean),
        broadcast: bodyVi.trim()
          ? { stage, body_vi: bodyVi, body_en: bodyEn, eta: etaUnknown ? null : fromLocal(etaAt), eta_unknown: etaUnknown }
          : null,
      });
      router.push(`/incidents/${made.public_id}`);
    } catch (e) {
      setError(e instanceof ApiError ? `${e.message}${e.code ? ` (${e.code})` : ""}` : "The incident wasn't declared. Try again.");
      setBusy(false);
    }
  }

  return (
    <Page width="form">
      <PageHeader
        eyebrow="Workspace / Incidents"
        vi="Khai báo sự cố"
        back={{ href: "/incidents", label: "Incidents" }}
        title="Declare an incident"
        description="Use this when monitoring or a call shows an outage before tickets pile up. It is confirmed at once, and similar new tickets attach to it automatically."
      />
      <form
        noValidate
        onSubmit={(e) => {
          e.preventDefault();
          void declare();
        }}
        className="flex flex-col gap-4"
      >
        {error && <ErrorState title="The incident wasn't declared">{error}</ErrorState>}
        <Panel title="What's happening">
          <div className="flex flex-col gap-4">
            <Labeled label="Incident name" required error={titleError}>
              <Input value={title} aria-invalid={!!titleError} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. VPN down for the Hanoi office" />
            </Labeled>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Labeled label="Category">
                <NativeSelect value={category} onChange={(e) => setCategory(e.target.value)}>
                  {CATEGORIES.map((c) => (
                    <option key={c}>{c}</option>
                  ))}
                </NativeSelect>
              </Labeled>
              <Labeled label="Affected service">
                <Input value={service} onChange={(e) => setService(e.target.value)} placeholder="e.g. GlobalProtect VPN" />
              </Labeled>
            </div>
            <Labeled label="Related tickets" hint="Ticket IDs, separated by commas or spaces.">
              <Input className="num" value={tickets} placeholder="TKT-2026-000440, TKT-2026-000441" onChange={(e) => setTickets(e.target.value)} />
            </Labeled>
          </div>
        </Panel>
        <Panel title="First update to affected people" aside={<span className="text-xs text-muted-foreground">Optional; sent when the Vietnamese message is filled in</span>}>
          <div className="flex flex-col gap-4">
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
              <Labeled label="Stage">
                <NativeSelect value={stage} onChange={(e) => setStage(e.target.value)}>
                  {STAGES.filter((s) => s !== "resolved").map((s) => (
                    <option key={s}>{s}</option>
                  ))}
                </NativeSelect>
              </Labeled>
              <Labeled label="Expected fix (ICT, +07)">
                <Input type="datetime-local" value={etaAt} disabled={etaUnknown} onChange={(e) => setEtaAt(e.target.value)} />
              </Labeled>
              <label className="flex min-h-9 items-center gap-2 text-sm">
                <Checkbox checked={etaUnknown} onCheckedChange={(checked) => setEtaUnknown(checked === true)} />
                Not known yet
              </label>
            </div>
            <Labeled label="Message (Vietnamese)">
              <Textarea lang="vi" className="min-h-20" value={bodyVi} onChange={(e) => setBodyVi(e.target.value)} />
            </Labeled>
            <Labeled label="Message (English, optional)">
              <Textarea className="min-h-16" value={bodyEn} onChange={(e) => setBodyEn(e.target.value)} />
            </Labeled>
          </div>
        </Panel>
        <div className="flex flex-col-reverse gap-2 sm:flex-row sm:justify-end">
          <Button type="button" variant="outline" onClick={() => router.push("/incidents")}>
            Cancel
          </Button>
          <Button type="submit" disabled={busy}>
            {busy ? "Declaring…" : "Declare incident"}
          </Button>
        </div>
      </form>
    </Page>
  );
}
