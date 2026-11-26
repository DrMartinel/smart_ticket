"use client";

// Customer companies (F17 §o): each a Keystone domain with a tier that raises a ticket's starting priority.

import { useCallback, useEffect, useState } from "react";
import Modal, { Labeled } from "@/components/Modal";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { NativeSelect } from "@/components/ui/native-select";
import { Page, PageHeader } from "@/components/ui/page-header";
import { EmptyState, ErrorState, TableStatus } from "@/components/ui/states";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Textarea } from "@/components/ui/textarea";
import { ApiError, api } from "@/lib/api";
import { useRequireAuth } from "@/lib/auth";
import { customerTierTone } from "@/lib/badges";
import { dateTime } from "@/lib/format";
import { P, can } from "@/lib/permissions";
import type { CustomerIn, CustomerListingOut, CustomerOut, CustomerPatch, CustomerTier } from "@/lib/types/generated";

const TIERS: CustomerTier[] = ["standard", "business", "enterprise"];

interface Draft {
  id: string | null;
  domain_id: string;
  heading: string;
  name: string;
  tier: CustomerTier;
  reason: string;
}

export default function CustomersPage() {
  const user = useRequireAuth();
  const [listing, setListing] = useState<CustomerListingOut | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      setListing(await api.get<CustomerListingOut>("/api/infra/customers"));
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? "You can't manage customers." : "Couldn't load the customers.");
    }
  }, []);

  useEffect(() => {
    if (user && can(user, P.infraCustomersManage)) void load();
  }, [user, load]);

  if (!user) return null;
  if (!can(user, P.infraCustomersManage)) {
    return (
      <Page width="record">
        <ErrorState title="You can't manage customers." />
      </Page>
    );
  }

  const save = async () => {
    if (!draft) return;
    setSaveError(null);
    try {
      if (draft.id) {
        const body: CustomerPatch = { name: draft.name.trim(), tier: draft.tier, reason: draft.reason.trim() };
        await api.patch<CustomerOut>(`/api/infra/customers/${draft.id}`, body);
      } else {
        const body: CustomerIn = { domain_id: draft.domain_id, name: draft.name.trim(), tier: draft.tier, reason: draft.reason.trim() };
        await api.post<CustomerOut>("/api/infra/customers", body);
      }
      setDraft(null);
      await load();
    } catch (err) {
      setSaveError(err instanceof ApiError ? err.message : "Couldn't save the customer.");
    }
  };

  const edit = (c: CustomerOut) => {
    setSaveError(null);
    setDraft({ id: c.id, domain_id: c.keystone_domain_id, heading: c.name, name: c.name, tier: c.tier, reason: "" });
  };

  const add = (domainId: string, domainName: string) => {
    setSaveError(null);
    setDraft({ id: null, domain_id: domainId, heading: domainName, name: domainName, tier: "standard", reason: "" });
  };

  const valid = !!draft?.name.trim() && !!draft?.reason.trim();

  return (
    <Page width="record" className="flex flex-col gap-4">
      <PageHeader
        className="mb-2"
        eyebrow="Admin / Settings"
        title="Customers"
        description="Each customer is a company's domain in the cloud. Its tier raises the starting priority of its people's tickets (enterprise starts at P2); it never lowers one, and tickets already handed off keep theirs."
      />

      {error && <ErrorState title={error} onRetry={() => { setError(null); void load(); }} />}
      {listing?.domains_unavailable && (
        <Alert variant="warn">
          <AlertDescription>
            Keystone didn&apos;t answer, so the cloud&apos;s domains aren&apos;t listed and no customer can be added. You can still change a customer&apos;s name or tier.
          </AlertDescription>
        </Alert>
      )}

      <Card className="overflow-x-auto">
        <Table className="min-w-[720px]">
          <TableHeader>
            <TableRow>
              <TableHead>Customer</TableHead>
              <TableHead>Tier</TableHead>
              <TableHead>Changed</TableHead>
              <TableHead />
            </TableRow>
          </TableHeader>
          <TableBody>
            <TableStatus
              colSpan={4}
              rows={listing?.customers ?? null}
              error={!!error}
              empty={<EmptyState compact title="No customers yet">Every ticket starts at the rule&apos;s priority.</EmptyState>}
            />
            {listing?.customers.map((c) => (
              <TableRow key={c.id}>
                <TableCell className="align-top">
                  <span className="font-medium">{c.name}</span>
                  <span className="block font-mono text-[11px] text-muted-foreground">{c.keystone_domain_id}</span>
                </TableCell>
                <TableCell className="align-top">
                  <Badge variant={customerTierTone(c.tier)}>{c.tier}</Badge>
                </TableCell>
                <TableCell className="align-top text-xs text-muted-foreground">{dateTime(c.updated_at)}</TableCell>
                <TableCell className="align-top text-right">
                  <Button variant="outline" size="sm" onClick={() => edit(c)}>
                    Edit
                  </Button>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </Card>

      {listing && listing.unclaimed_domains.length > 0 && (
        <Card className="overflow-x-auto">
          <Table className="min-w-[720px]">
            <TableHeader>
              <TableRow>
                <TableHead>Cloud domains with no customer</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {listing.unclaimed_domains.map((d) => (
                <TableRow key={d.id}>
                  <TableCell>
                    <span className="font-medium">{d.name}</span>
                    <span className="block font-mono text-[11px] text-muted-foreground">{d.id}</span>
                  </TableCell>
                  <TableCell className="text-right">
                    <Button variant="outline" size="sm" onClick={() => add(d.id, d.name)}>
                      Add as customer
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </Card>
      )}

      <Modal
        open={!!draft}
        onClose={() => setDraft(null)}
        title={draft?.id ? `Edit ${draft.heading}` : "Add a customer"}
        subtitle={draft?.id ? "A new tier applies to tickets handed off from now on." : `Domain ${draft?.heading ?? ""}`}
        footer={
          <>
            <Button variant="outline" onClick={() => setDraft(null)}>
              Cancel
            </Button>
            <Button disabled={!valid} onClick={() => void save()}>
              Save
            </Button>
          </>
        }
      >
        {draft && (
          <div className="flex flex-col gap-3">
            <Labeled label="Name" required>
              <Input value={draft.name} maxLength={120} onChange={(e) => setDraft({ ...draft, name: e.target.value })} />
            </Labeled>
            <Labeled label="Tier" required hint="Enterprise tickets start at P2 or higher; the others at the rule's priority.">
              <NativeSelect value={draft.tier} onChange={(e) => setDraft({ ...draft, tier: e.target.value as CustomerTier })}>
                {TIERS.map((t) => (
                  <option key={t} value={t}>
                    {t}
                  </option>
                ))}
              </NativeSelect>
            </Labeled>
            <Labeled label="Reason" required>
              <Textarea value={draft.reason} maxLength={500} onChange={(e) => setDraft({ ...draft, reason: e.target.value })} />
            </Labeled>
            {saveError && <ErrorState compact title="The customer wasn't saved">{saveError}</ErrorState>}
          </div>
        )}
      </Modal>
    </Page>
  );
}
