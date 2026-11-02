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

  if (!user) return null;
  if (!user.capabilities?.includes("incident_manager")) {
    return <p className="text-sm text-muted-foreground">Chỉ người quản lý sự cố được khai báo sự cố.</p>;
  }

  async function declare() {
    setBusy(true);
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
      setError(e instanceof ApiError ? `${e.code ?? e.status}: ${e.message}` : "Không khai báo được.");
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex max-w-[760px] flex-col gap-4">
      <header>
        <h1 className="text-xl font-semibold">Khai báo sự cố · Declare an incident</h1>
        <p className="text-xs text-muted-foreground">
          Khi giám sát hoặc một cuộc gọi cho thấy sự cố trước khi phiếu dồn về. Sự cố được xác nhận ngay; phiếu mới tương tự sẽ tự gắn vào.
        </p>
      </header>
      {error && <p className="text-sm text-danger">{error}</p>}
      <Card asChild>
        <section className="flex flex-col gap-3 px-4 py-4 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Tên sự cố</span>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Category</span>
              <NativeSelect value={category} onChange={(e) => setCategory(e.target.value)}>
                {CATEGORIES.map((c) => (
                  <option key={c}>{c}</option>
                ))}
              </NativeSelect>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Dịch vụ bị ảnh hưởng</span>
              <Input value={service} onChange={(e) => setService(e.target.value)} />
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Phiếu liên quan (mã phiếu, cách nhau bởi dấu phẩy)</span>
            <Input className="font-mono" value={tickets} placeholder="TKT-2026-000440, TKT-2026-000441" onChange={(e) => setTickets(e.target.value)} />
          </label>
        </section>
      </Card>
      <Card asChild>
        <section className="flex flex-col gap-3 px-4 py-4 text-sm">
          <h2 className="font-semibold">Cập nhật đầu tiên</h2>
          <div className="flex flex-wrap gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">Stage</span>
              <NativeSelect value={stage} onChange={(e) => setStage(e.target.value)}>
                {STAGES.filter((s) => s !== "resolved").map((s) => (
                  <option key={s}>{s}</option>
                ))}
              </NativeSelect>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">ETA (+07)</span>
              <Input type="datetime-local" value={etaAt} disabled={etaUnknown} onChange={(e) => setEtaAt(e.target.value)} />
            </label>
            <label className="flex items-center gap-2 self-end pb-2">
              <Checkbox checked={etaUnknown} onCheckedChange={(checked) => setEtaUnknown(checked === true)} />
              chưa xác định
            </label>
          </div>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Nội dung (vi)</span>
            <Textarea className="min-h-16" value={bodyVi} onChange={(e) => setBodyVi(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">Message (en, optional)</span>
            <Textarea className="min-h-12" value={bodyEn} onChange={(e) => setBodyEn(e.target.value)} />
          </label>
        </section>
      </Card>
      <div className="flex justify-end">
        <Button disabled={busy || title.trim().length < 3} onClick={declare}>
          Khai báo
        </Button>
      </div>
    </div>
  );
}
